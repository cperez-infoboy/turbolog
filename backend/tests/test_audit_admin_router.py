"""Black-box tests for the admin audit router (RED phase).

Covers:
- GET /api/audit/users lists all users with flags.
- PATCH /api/audit/users/{id} sets is_audited / promotes/demotes is_admin.
- Anti-lockout: demoting the last non-seed admin -> 409.
- Super-admin seed is immutable: PATCH is_admin=False on a seed user -> stays admin.
- GET /api/audit/monthly only includes is_audited=True users.
- POST /api/audit/run-reminders -> 200 (job stubbed).
- Non-admin caller -> 403 on every endpoint.
"""
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.config import settings
from app.dependencies import get_current_user
from app.models.allowed_email import AllowedEmail
from app.models.user import User
from app.routers import audit as audit_router


# --------------------------------------------------------------------------- #
# App/client fixtures: wires the AUDIT router to the in-memory session factory.
# `app`/`client` => caller is a NON-admin (for 403 tests).
# `admin_app`/`admin_client` => caller is a DB-flag admin.
# --------------------------------------------------------------------------- #


def _build_app(session_factory):
    """Build a FastAPI app with the audit router wired to the in-memory DB."""
    audit_router.async_session = session_factory
    test_app = FastAPI()
    test_app.include_router(audit_router.router)
    return test_app


def _bind_user(test_app, session_factory, user_id: str) -> None:
    """Override get_current_user so the caller resolves to the given user."""

    async def _override_user():
        async with session_factory() as s:
            result = await s.execute(select(User).where(User.id == user_id))
            return result.scalar_one()

    test_app.dependency_overrides[get_current_user] = _override_user


@pytest_asyncio.fixture
async def app(session_factory, test_user):
    """Audit app where the caller is the non-admin `test_user`."""
    test_app = _build_app(session_factory)
    _bind_user(test_app, session_factory, test_user.id)
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_app(session_factory, test_user):
    """Audit app where the caller is promoted to DB-flag admin."""
    async with session_factory() as s:
        dbu = (await s.execute(select(User).where(User.id == test_user.id))).scalar_one()
        dbu.is_admin = True
        await s.commit()

    test_app = _build_app(session_factory)
    _bind_user(test_app, session_factory, test_user.id)
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(admin_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(
    session_factory,
    email: str,
    *,
    name: str = "N",
    is_admin: bool = False,
    is_audited: bool = False,
    google_sub: str | None = None,
) -> User:
    async with session_factory() as s:
        user = User(
            google_sub=google_sub or f"sub-{email}",
            email=email,
            name=name,
            is_admin=is_admin,
            is_audited=is_audited,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _fetch_user(session_factory, user_id: str) -> User:
    async with session_factory() as s:
        return (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one()


async def _seed_allowed_email(
    session_factory,
    email: str,
    *,
    added_by: str | None = None,
) -> AllowedEmail:
    async with session_factory() as s:
        row = AllowedEmail(email=email.strip().lower(), added_by=added_by)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


# --------------------------------------------------------------------------- #
# Access control: non-admin -> 403
# --------------------------------------------------------------------------- #


class TestAccessControl:
    async def test_non_admin_gets_403_on_users(self, client):
        resp = await client.get("/api/audit/users")
        assert resp.status_code == 403

    async def test_non_admin_gets_403_on_monthly(self, client):
        resp = await client.get("/api/audit/monthly", params={"year": 2026, "month": 6})
        assert resp.status_code == 403

    async def test_non_admin_gets_403_on_run_reminders(self, client):
        resp = await client.post("/api/audit/run-reminders")
        assert resp.status_code == 403

    async def test_non_admin_gets_403_on_patch(self, client):
        resp = await client.patch("/api/audit/users/some-id", json={"is_audited": True})
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# GET /users
# --------------------------------------------------------------------------- #


class TestListUsers:
    async def test_lists_all_users_with_flags(self, admin_client, session_factory):
        await _seed_user(session_factory, "a@x.com", is_admin=True, is_audited=False)
        await _seed_user(session_factory, "b@x.com", is_admin=False, is_audited=True)

        resp = await admin_client.get("/api/audit/users")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        emails = {u["email"] for u in body}
        assert {"tester@example.com", "a@x.com", "b@x.com"} <= emails
        # Flags reflect DB state.
        a = next(u for u in body if u["email"] == "a@x.com")
        assert a["is_admin"] is True
        assert a["is_audited"] is False
        b = next(u for u in body if u["email"] == "b@x.com")
        assert b["is_admin"] is False
        assert b["is_audited"] is True

    async def test_reflected_is_admin_includes_seed(
        self, admin_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "seed@x.com")
        await _seed_user(session_factory, "seed@x.com", is_admin=False)

        resp = await admin_client.get("/api/audit/users")
        assert resp.status_code == 200
        seed = next(u for u in resp.json() if u["email"] == "seed@x.com")
        assert seed["is_admin"] is True  # reflected from seed even though DB flag is False

    async def test_users_is_seed_flag(
        self, admin_client, session_factory, monkeypatch
    ):
        """GET /api/audit/users returns is_seed: True for seed, False otherwise."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "seed@x.com")
        await _seed_user(session_factory, "seed@x.com", is_admin=False)
        await _seed_user(session_factory, "mortal@x.com", is_admin=False)

        resp = await admin_client.get("/api/audit/users")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seed = next(u for u in body if u["email"] == "seed@x.com")
        assert seed["is_seed"] is True
        mortal = next(u for u in body if u["email"] == "mortal@x.com")
        assert mortal["is_seed"] is False


# --------------------------------------------------------------------------- #
# PATCH /users/{id}
# --------------------------------------------------------------------------- #


class TestPatchUser:
    async def test_set_is_audited_persists(self, admin_client, session_factory):
        target = await _seed_user(session_factory, "dev@x.com")

        resp = await admin_client.patch(
            f"/api/audit/users/{target.id}", json={"is_audited": True}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_audited"] is True

        db_target = await _fetch_user(session_factory, target.id)
        assert db_target.is_audited is True

    async def test_promote_to_admin_sticks(self, admin_client, session_factory):
        target = await _seed_user(session_factory, "dev@x.com", is_admin=False)

        resp = await admin_client.patch(
            f"/api/audit/users/{target.id}", json={"is_admin": True}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_admin"] is True

        db_target = await _fetch_user(session_factory, target.id)
        assert db_target.is_admin is True

    async def test_patch_unknown_user_404(self, admin_client):
        resp = await admin_client.patch(
            "/api/audit/users/nonexistent", json={"is_audited": True}
        )
        assert resp.status_code == 404

    async def test_anti_lockout_last_admin_409(
        self, admin_app, session_factory, monkeypatch
    ):
        """Demoting the only non-seed admin to is_admin=False -> 409.

        The admin_client caller (test_user) is itself a non-seed admin, so to
        isolate "last admin" we clear the seed and make target the ONLY admin.
        We re-bind the caller to be the target admin, then try to demote it.
        """
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")  # no seed admins
        # Remove admin flag from the default test_user so target is the sole admin.
        async with session_factory() as s:
            default = (
                await s.execute(select(User).where(User.email == "tester@example.com"))
            ).scalar_one()
            default.is_admin = False
            await s.commit()

        target = await _seed_user(session_factory, "only-admin@x.com", is_admin=True)
        _bind_user(admin_app, session_factory, target.id)

        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.patch(
                f"/api/audit/users/{target.id}", json={"is_admin": False}
            )
        assert resp.status_code == 409
        assert "last admin" in resp.json()["detail"].lower()

    async def test_anti_lockout_allows_demote_when_other_admins_exist(
        self, admin_client, session_factory, monkeypatch
    ):
        """Demoting a non-seed admin is OK when another non-seed admin exists.

        The admin_client caller (test_user) is already a non-seed admin; we seed
        a second one and demote it. Two non-seed admins => demotion allowed.
        """
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        await _seed_user(session_factory, "b@x.com", is_admin=True)

        b = await _fetch_user_by_email(session_factory, "b@x.com")
        resp = await admin_client.patch(
            f"/api/audit/users/{b.id}", json={"is_admin": False}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_admin"] is False

    async def test_seed_immutable_stays_admin(
        self, admin_client, session_factory, monkeypatch
    ):
        """PATCH is_admin=False on a seed user -> 200 but stays admin."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "seed@x.com")
        seed_user = await _seed_user(session_factory, "seed@x.com", is_admin=False)

        resp = await admin_client.patch(
            f"/api/audit/users/{seed_user.id}", json={"is_admin": False}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_admin"] is True  # still admin (seed immutable)


async def _fetch_user_by_email(session_factory, email: str) -> User:
    async with session_factory() as s:
        return (
            await s.execute(select(User).where(User.email == email))
        ).scalar_one()


# --------------------------------------------------------------------------- #
# GET /allowed-emails
# --------------------------------------------------------------------------- #


class TestListAllowedEmails:
    async def test_allowed_emails_is_seed_flag(
        self, admin_client, session_factory, monkeypatch
    ):
        """GET /api/audit/allowed-emails returns is_seed for seed vs normal."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "seed@x.com")
        await _seed_allowed_email(session_factory, "seed@x.com")
        await _seed_allowed_email(session_factory, "normal@x.com")

        resp = await admin_client.get("/api/audit/allowed-emails")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seed = next(e for e in body if e["email"] == "seed@x.com")
        assert seed["is_seed"] is True
        normal = next(e for e in body if e["email"] == "normal@x.com")
        assert normal["is_seed"] is False


# --------------------------------------------------------------------------- #
# GET /monthly
# --------------------------------------------------------------------------- #


class TestMonthlyReport:
    async def test_monthly_only_audited_users(
        self, admin_client, session_factory, monkeypatch
    ):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
        # Isolate from the production .env: AUDIT_TIMEZONE may carry an invalid
        # tzdb key. Pin a valid one so the endpoint's "today" resolves.
        monkeypatch.setattr(settings, "AUDIT_TIMEZONE", "America/Santiago")
        await _seed_user(
            session_factory, "audited@x.com", is_audited=True, google_sub="g-audited"
        )
        await _seed_user(
            session_factory, "plain@x.com", is_audited=False, google_sub="g-plain"
        )

        resp = await admin_client.get(
            "/api/audit/monthly", params={"year": 2026, "month": 6}
        )
        assert resp.status_code == 200, resp.text
        emails = {entry["user_email"] for entry in resp.json()}
        assert "audited@x.com" in emails
        assert "plain@x.com" not in emails

    async def test_monthly_bad_month_400(self, admin_client):
        resp = await admin_client.get(
            "/api/audit/monthly", params={"year": 2026, "month": 13}
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# POST /run-reminders
# --------------------------------------------------------------------------- #


class TestRunReminders:
    async def test_run_reminders_200(
        self, admin_client, monkeypatch
    ):
        # Stub run_reminder_job on the audit module so the real job doesn't run.
        called = {"n": 0}

        async def _fake_run(notifier):
            called["n"] += 1

        monkeypatch.setattr(audit_router, "run_reminder_job", _fake_run)

        resp = await admin_client.post("/api/audit/run-reminders")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "done"}
        assert called["n"] == 1
