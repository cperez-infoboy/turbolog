"""Tests for the admin seed bootstrap in the auth router.

Security model (after fix):
- `POST /api/auth/register` NEVER grants admin -- the email comes from the
  client body and is not trusted. New users are always created is_admin=False.
- Admin is granted ONLY from a Google-verified email, either:
  * in `GET /api/auth/google/callback` for an existing seed user (promotion on
    login via `apply_seed_admin`), or
  * in `google_callback` for a new seed user (created directly with
    is_admin=True, skipping /register).
- `/me` still reports is_admin based on DB flag OR seed membership.

Covers:
- register with an email in ADMIN_EMAILS -> created user is_admin=False.
- register with an email NOT in seed -> is_admin=False.
- GET /api/auth/me returns is_admin reflecting the seed/flag.
- A DB-flag admin (is_admin=True) is reported even when seed is empty.
- apply_seed_admin: grant semantics (promote non-admin seed user; idempotent on
  already-admin; never revoke; non-seed unchanged).
- email_in_seed: case-insensitive, trimmed.
"""
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.routers import auth as auth_router


# --------------------------------------------------------------------------- #
# Local app fixture: wires the AUTH router to the in-memory DB (mirrors the
# status-router fixture in conftest.py, but for the auth router).
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def auth_app(session_factory):
    """FastAPI app with the auth router wired to the in-memory session factory."""
    auth_router.async_session = session_factory
    test_app = FastAPI()
    test_app.include_router(auth_router.router)
    yield test_app


@pytest_asyncio.fixture
async def auth_client(auth_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """httpx AsyncClient talking to the auth test app via ASGITransport."""
    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register_payload(email: str, google_sub: str = "sub-x") -> dict:
    return {
        "google_sub": google_sub,
        "email": email,
        "name": "Test User",
        "picture": None,
    }


async def _fetch_user(session_factory, email: str) -> User:
    async with session_factory() as s:
        result = await s.execute(select(User).where(User.email == email))
        return result.scalar_one()


async def _allow_email(session_factory, email: str) -> None:
    """Pre-authorize an email in allowed_emails so the register gate passes.

    These tests target admin-seed grant semantics, not the access-control gate.
    The gate (introduced separately) requires authorization; seeding the row
    here preserves the tests' original intent.
    """
    from app.models.allowed_email import AllowedEmail

    async with session_factory() as s:
        s.add(AllowedEmail(email=email.strip().lower()))
        await s.commit()


async def _login_as(auth_app, session_factory, user_id: str) -> None:
    """Override get_current_user so /me resolves to the seeded user."""
    from app.dependencies import get_current_user as _get_current_user

    async def _override_user():
        async with session_factory() as s:
            result = await s.execute(select(User).where(User.id == user_id))
            return result.scalar_one()

    auth_app.dependency_overrides[_get_current_user] = _override_user


# --------------------------------------------------------------------------- #
# register -> NEVER grants admin (email comes from client body, untrusted)
# --------------------------------------------------------------------------- #


class TestRegisterNeverGrantsAdmin:
    async def test_seed_email_is_not_admin_via_register(
        self, auth_client, session_factory, monkeypatch
    ):
        """Security: a seed email posted to the public /register endpoint must
        NOT yield an admin. Admin is only granted from Google-verified email."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("Boss@Company.com")
        )
        assert resp.status_code == 200, resp.text

        user = await _fetch_user(session_factory, "Boss@Company.com")
        assert user.is_admin is False

    async def test_non_seed_email_is_not_admin(
        self, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        await _allow_email(session_factory, "dev@company.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("dev@company.com")
        )
        assert resp.status_code == 200, resp.text

        user = await _fetch_user(session_factory, "dev@company.com")
        assert user.is_admin is False

    async def test_multiple_seed_emails_not_admin_via_register(
        self, auth_client, session_factory, monkeypatch
    ):
        """Even with several seed addresses, /register creates non-admins."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "a@x.com, b@x.com ,, c@x.com")
        for i, email in enumerate(("a@x.com", "B@X.com", "c@x.com")):
            resp = await auth_client.post(
                "/api/auth/register",
                json=_register_payload(email, google_sub=f"sub-{i}"),
            )
            assert resp.status_code == 200, resp.text
            user = await _fetch_user(session_factory, email)
            assert user.is_admin is False, f"{email} must NOT be admin via /register"

    async def test_empty_seed_makes_nobody_admin(
        self, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _allow_email(session_factory, "anyone@x.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("anyone@x.com")
        )
        assert resp.status_code == 200, resp.text
        user = await _fetch_user(session_factory, "anyone@x.com")
        assert user.is_admin is False


# --------------------------------------------------------------------------- #
# /me -> is_admin
# --------------------------------------------------------------------------- #


class TestMeIsAdmin:
    async def test_me_reflects_db_flag_true(
        self, auth_app, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        # Register a user (non-admin), then flip the DB flag to simulate an
        # admin promoted via the (future) management endpoint.
        await _allow_email(session_factory, "promoted@x.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("promoted@x.com")
        )
        assert resp.status_code == 200
        user_id = resp.json()["user_id"]

        async with session_factory() as s:
            db_user = (
                await s.execute(select(User).where(User.id == user_id))
            ).scalar_one()
            db_user.is_admin = True
            await s.commit()

        await _login_as(auth_app, session_factory, user_id)

        me_resp = await auth_client.get("/api/auth/me")
        assert me_resp.status_code == 200, me_resp.text
        assert me_resp.json()["is_admin"] is True

    async def test_me_reflects_seed_even_without_db_flag(
        self, auth_app, auth_client, session_factory, monkeypatch
    ):
        # A seed email registered before ADMIN_EMAILS was set: is_admin=False
        # in DB, but /me should still report True because the email is in seed.
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _allow_email(session_factory, "legacy@x.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("legacy@x.com")
        )
        assert resp.status_code == 200
        user_id = resp.json()["user_id"]

        # Now add this email to the seed (simulating .env change after registration).
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "legacy@x.com")

        await _login_as(auth_app, session_factory, user_id)

        me_resp = await auth_client.get("/api/auth/me")
        assert me_resp.status_code == 200, me_resp.text
        assert me_resp.json()["is_admin"] is True

    async def test_me_false_for_non_admin(
        self, auth_app, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@x.com")
        await _allow_email(session_factory, "plain@x.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("plain@x.com")
        )
        assert resp.status_code == 200
        user_id = resp.json()["user_id"]

        await _login_as(auth_app, session_factory, user_id)

        me_resp = await auth_client.get("/api/auth/me")
        assert me_resp.status_code == 200, me_resp.text
        assert me_resp.json()["is_admin"] is False


# --------------------------------------------------------------------------- #
# apply_seed_admin (pure helper unit tests)
# --------------------------------------------------------------------------- #


class TestApplySeedAdmin:
    """Unit tests for app.routers.auth.apply_seed_admin.

    Contract: only ever GRANTS (never revokes a DB-granted admin). Returns
    True if the user was promoted, False otherwise.
    """

    async def test_promotes_seed_non_admin_user(
        self, session_factory, monkeypatch
    ):
        from app.routers.auth import apply_seed_admin

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        async with session_factory() as session:
            user = User(
                id="u-promote",
                google_sub="g-promote",
                email="Boss@Company.com",  # case-different from seed
                name="Boss",
                is_admin=False,
            )
            session.add(user)
            await session.commit()

            changed = await apply_seed_admin(session, user)
            assert changed is True
            assert user.is_admin is True

        # Persisted across sessions.
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.id == "u-promote"))
            db_user = result.scalar_one()
            assert db_user.is_admin is True

    async def test_non_seed_user_unchanged(self, session_factory, monkeypatch):
        from app.routers.auth import apply_seed_admin

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        async with session_factory() as session:
            user = User(
                id="u-plain",
                google_sub="g-plain",
                email="dev@company.com",
                name="Dev",
                is_admin=False,
            )
            session.add(user)
            await session.commit()

            changed = await apply_seed_admin(session, user)
            assert changed is False
            assert user.is_admin is False

    async def test_already_admin_seed_user_unchanged(self, session_factory, monkeypatch):
        """A seed user who is already admin: no change, returns False."""
        from app.routers.auth import apply_seed_admin

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        async with session_factory() as session:
            user = User(
                id="u-already",
                google_sub="g-already",
                email="boss@company.com",
                name="Boss",
                is_admin=True,
            )
            session.add(user)
            await session.commit()

            changed = await apply_seed_admin(session, user)
            assert changed is False
            assert user.is_admin is True

    async def test_never_revokes_admin_whose_email_left_seed(
        self, session_factory, monkeypatch
    ):
        """A user who was granted admin in DB but whose email is no longer in
        the seed must NOT be demoted by apply_seed_admin."""
        from app.routers.auth import apply_seed_admin

        # Seed is now empty -- this email is no longer seeded.
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        async with session_factory() as session:
            user = User(
                id="u-revoke-guard",
                google_sub="g-revoke",
                email="former-admin@company.com",
                name="Former",
                is_admin=True,
            )
            session.add(user)
            await session.commit()

            changed = await apply_seed_admin(session, user)
            assert changed is False
            assert user.is_admin is True

    async def test_empty_seed_never_promotes(self, session_factory, monkeypatch):
        from app.routers.auth import apply_seed_admin

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        async with session_factory() as session:
            user = User(
                id="u-empty-seed",
                google_sub="g-empty",
                email="anyone@company.com",
                name="Any",
                is_admin=False,
            )
            session.add(user)
            await session.commit()

            changed = await apply_seed_admin(session, user)
            assert changed is False
            assert user.is_admin is False


# --------------------------------------------------------------------------- #
# email_in_seed (pure helper unit tests)
# --------------------------------------------------------------------------- #


class TestEmailInSeed:
    def test_case_insensitive_match(self, monkeypatch):
        from app.routers.auth import email_in_seed

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        assert email_in_seed("Boss@Company.com") is True
        assert email_in_seed("BOSS@COMPANY.COM") is True
        assert email_in_seed("boss@company.com") is True

    def test_trimmed(self, monkeypatch):
        from app.routers.auth import email_in_seed

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        assert email_in_seed("  boss@company.com  ") is True

    def test_non_match(self, monkeypatch):
        from app.routers.auth import email_in_seed

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        assert email_in_seed("dev@company.com") is False

    def test_empty_seed(self, monkeypatch):
        from app.routers.auth import email_in_seed

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        assert email_in_seed("anyone@company.com") is False

    def test_multiple_seeds(self, monkeypatch):
        from app.routers.auth import email_in_seed

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "a@x.com, b@x.com ,, c@x.com")
        assert email_in_seed("B@X.com") is True
        assert email_in_seed("c@x.com") is True
        assert email_in_seed("d@x.com") is False
