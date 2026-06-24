"""Access-control (email allow-list) tests (RED phase).

Covers:
- ``can_login`` helper: seed email passes even without a row; a row passes;
  neither fails; case-insensitive and trimmed.
- ``register`` gate: a non-allowed email is rejected with 403 and NO user is
  created; an allowed email (seeded into allowed_emails) registers fine.
- Admin allow-list endpoints on the audit router: GET lists, POST adds +
  normalizes + is idempotent, DELETE removes (404 if missing), non-admin -> 403.

``google_callback`` itself is NOT unit-tested (it mocks Google) -- its gate is
covered transitively via ``can_login`` and the ``register`` defense.
"""
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.config import settings
from app.dependencies import can_login, get_current_user
from app.models.allowed_email import AllowedEmail
from app.models.user import User
from app.routers import audit as audit_router
from app.routers import auth as auth_router


# --------------------------------------------------------------------------- #
# App/client fixtures (mirror test_audit_admin_router.py / test_auth_admin_seed.py)
# --------------------------------------------------------------------------- #


def _build_audit_app(session_factory):
    audit_router.async_session = session_factory
    test_app = FastAPI()
    test_app.include_router(audit_router.router)
    return test_app


def _bind_user(test_app, session_factory, user_id: str) -> None:
    async def _override_user():
        async with session_factory() as s:
            result = await s.execute(select(User).where(User.id == user_id))
            return result.scalar_one()

    test_app.dependency_overrides[get_current_user] = _override_user


@pytest_asyncio.fixture
async def auth_app(session_factory):
    """Auth router wired to the in-memory session factory."""
    auth_router.async_session = session_factory
    test_app = FastAPI()
    test_app.include_router(auth_router.router)
    yield test_app


@pytest_asyncio.fixture
async def auth_client(auth_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_app(session_factory, test_user):
    """Audit app where the caller (test_user) is promoted to DB-flag admin."""
    async with session_factory() as s:
        dbu = (await s.execute(select(User).where(User.id == test_user.id))).scalar_one()
        dbu.is_admin = True
        await s.commit()

    test_app = _build_audit_app(session_factory)
    _bind_user(test_app, session_factory, test_user.id)
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(admin_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def nonadmin_app(session_factory, test_user):
    """Audit app where the caller is the non-admin test_user (for 403 tests)."""
    test_app = _build_audit_app(session_factory)
    _bind_user(test_app, session_factory, test_user.id)
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def nonadmin_client(nonadmin_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=nonadmin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_allowed(session_factory, email: str, added_by: str | None = None) -> AllowedEmail:
    async with session_factory() as s:
        row = AllowedEmail(email=email.strip().lower(), added_by=added_by)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def _fetch_allowed(session_factory, email: str) -> AllowedEmail | None:
    async with session_factory() as s:
        result = await s.execute(
            select(AllowedEmail).where(AllowedEmail.email == email.strip().lower())
        )
        return result.scalar_one_or_none()


async def _count_allowed(session_factory) -> int:
    from sqlalchemy import func

    async with session_factory() as s:
        return (
            await s.execute(select(func.count()).select_from(AllowedEmail))
        ).scalar_one()


def _register_payload(email: str, google_sub: str = "sub-x") -> dict:
    return {
        "google_sub": google_sub,
        "email": email,
        "name": "Test User",
        "picture": None,
    }


# --------------------------------------------------------------------------- #
# can_login helper
# --------------------------------------------------------------------------- #


class TestCanLogin:
    async def test_seed_email_passes_without_row(self, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        async with session_factory() as session:
            assert await can_login(session, "boss@company.com") is True

    async def test_seed_email_case_insensitive_and_trimmed(
        self, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        async with session_factory() as session:
            assert await can_login(session, "  Boss@Company.com  ") is True
            assert await can_login(session, "BOSS@COMPANY.COM") is True

    async def test_row_passes(self, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _seed_allowed(session_factory, "dev@company.com")
        async with session_factory() as session:
            assert await can_login(session, "dev@company.com") is True

    async def test_row_case_insensitive_and_trimmed(self, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _seed_allowed(session_factory, "dev@company.com")
        async with session_factory() as session:
            assert await can_login(session, "  Dev@Company.com  ") is True

    async def test_neither_seed_nor_row_fails(self, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        await _seed_allowed(session_factory, "dev@company.com")
        async with session_factory() as session:
            assert await can_login(session, "intruder@company.com") is False

    async def test_empty_seed_and_empty_table_fails(self, session_factory, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        async with session_factory() as session:
            assert await can_login(session, "nobody@company.com") is False


# --------------------------------------------------------------------------- #
# register gate
# --------------------------------------------------------------------------- #


class TestRegisterGate:
    async def test_non_allowed_email_is_403_and_no_user_created(
        self, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("intruder@company.com")
        )
        assert resp.status_code == 403, resp.text

        # No user row was created.
        async with session_factory() as s:
            result = await s.execute(
                select(User).where(User.email == "intruder@company.com")
            )
            assert result.scalar_one_or_none() is None

    async def test_allowed_email_registers_ok(
        self, auth_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        await _seed_allowed(session_factory, "dev@company.com")

        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("dev@company.com")
        )
        assert resp.status_code == 200, resp.text

        async with session_factory() as s:
            user = (
                await s.execute(select(User).where(User.email == "dev@company.com"))
            ).scalar_one()
            assert user.is_admin is False  # register never grants admin

    async def test_seed_email_registers_ok_via_register(
        self, auth_client, session_factory, monkeypatch
    ):
        """Seed emails pass the gate (defense in depth; admin granted elsewhere)."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")
        resp = await auth_client.post(
            "/api/auth/register", json=_register_payload("boss@company.com")
        )
        assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# Admin allow-list endpoints -- access control (non-admin -> 403)
# --------------------------------------------------------------------------- #


class TestAllowedEmailsAccessControl:
    async def test_non_admin_get_403(self, nonadmin_client):
        resp = await nonadmin_client.get("/api/audit/allowed-emails")
        assert resp.status_code == 403

    async def test_non_admin_post_403(self, nonadmin_client):
        resp = await nonadmin_client.post(
            "/api/audit/allowed-emails", json={"email": "x@x.com"}
        )
        assert resp.status_code == 403

    async def test_non_admin_delete_403(self, nonadmin_client):
        resp = await nonadmin_client.delete("/api/audit/allowed-emails/x@x.com")
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Admin allow-list endpoints -- GET
# --------------------------------------------------------------------------- #


class TestAllowedEmailsList:
    async def test_lists_ordered_by_email_with_shape(
        self, admin_client, session_factory, test_user
    ):
        await _seed_allowed(session_factory, "zeta@x.com")
        await _seed_allowed(session_factory, "alpha@x.com", added_by=test_user.id)

        resp = await admin_client.get("/api/audit/allowed-emails")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, list)
        emails = [entry["email"] for entry in body]
        assert emails == sorted(emails)  # ordered
        assert "alpha@x.com" in emails and "zeta@x.com" in emails

        alpha = next(e for e in body if e["email"] == "alpha@x.com")
        assert alpha["added_by"] == test_user.id
        assert alpha["created_at"]


# --------------------------------------------------------------------------- #
# Admin allow-list endpoints -- POST
# --------------------------------------------------------------------------- #


class TestAllowedEmailsAdd:
    async def test_adds_normalizes_and_records_added_by(
        self, admin_client, session_factory, test_user
    ):
        resp = await admin_client.post(
            "/api/audit/allowed-emails", json={"email": "  Dev@Company.com  "}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["email"] == "dev@company.com"  # normalized
        assert body["added_by"] == test_user.id
        assert body["created_at"]

        row = await _fetch_allowed(session_factory, "dev@company.com")
        assert row is not None
        assert row.added_by == test_user.id

    async def test_idempotent_returns_existing_row(
        self, admin_client, session_factory, test_user
    ):
        first = await admin_client.post(
            "/api/audit/allowed-emails", json={"email": "dev@x.com"}
        )
        assert first.status_code == 200
        first_id = (await _fetch_allowed(session_factory, "dev@x.com")).id

        second = await admin_client.post(
            "/api/audit/allowed-emails", json={"email": "DEV@X.com"}
        )
        assert second.status_code == 200, second.text
        # Idempotent: still exactly one row with the same id.
        assert (await _fetch_allowed(session_factory, "dev@x.com")).id == first_id
        assert await _count_allowed(session_factory) == 1

    async def test_rejects_empty_email(self, admin_client):
        resp = await admin_client.post(
            "/api/audit/allowed-emails", json={"email": "   "}
        )
        assert resp.status_code in (400, 422)

    async def test_can_login_after_add(self, admin_client, session_factory, monkeypatch):
        """Adding an email via the endpoint makes can_login accept it."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await admin_client.post(
            "/api/audit/allowed-emails", json={"email": "newmate@x.com"}
        )
        async with session_factory() as session:
            assert await can_login(session, "newmate@x.com") is True


# --------------------------------------------------------------------------- #
# Admin allow-list endpoints -- DELETE
# --------------------------------------------------------------------------- #


class TestAllowedEmailsDelete:
    async def test_deletes_existing(self, admin_client, session_factory):
        await _seed_allowed(session_factory, "dev@x.com")
        resp = await admin_client.delete("/api/audit/allowed-emails/DEV@X.com")
        assert resp.status_code == 200, resp.text
        assert await _fetch_allowed(session_factory, "dev@x.com") is None

    async def test_delete_missing_returns_404(self, admin_client):
        resp = await admin_client.delete("/api/audit/allowed-emails/ghost@x.com")
        assert resp.status_code == 404

    async def test_delete_revokes_can_login(self, admin_client, session_factory, monkeypatch):
        """Removing an email blocks it from logging in (real revocation)."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _seed_allowed(session_factory, "dev@x.com")
        await admin_client.delete("/api/audit/allowed-emails/dev@x.com")

        async with session_factory() as session:
            assert await can_login(session, "dev@x.com") is False
