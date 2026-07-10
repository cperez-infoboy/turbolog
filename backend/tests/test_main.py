"""Tests for app.main wiring: CORS parameterization, schema-tolerant seed,
and the prod-only assert_prod_secrets gate in the lifespan.

Design refinement vs. the unconditional assert: the gate runs ONLY when
``/run/secrets`` exists (prod). Dev has no such dir, so the assertion never
fires there — local boot is unaffected by insecure-default values.
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _async_noop() -> None:
    return None


# --------------------------------------------------------------------------- #
# CORS parameterization
# --------------------------------------------------------------------------- #


class TestCorsParameterized:
    def test_allow_origins_derived_from_settings_via_split(self):
        # The middleware must receive a LIST derived from settings.CORS_ORIGINS
        # (split on comma), not a hard-coded list and not the raw string.
        from starlette.middleware.cors import CORSMiddleware

        from app.main import app

        cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        allow_origins = cors.kwargs["allow_origins"]
        assert isinstance(allow_origins, list)
        assert allow_origins == settings.CORS_ORIGINS.split(",")


# --------------------------------------------------------------------------- #
# Schema-tolerant seed (_seed_admin_allowed_emails)
# --------------------------------------------------------------------------- #


class TestSeedSchemaTolerant:
    async def test_does_not_raise_when_allowed_emails_table_absent(self, monkeypatch):
        # Build an engine that has every model table EXCEPT allowed_emails
        # (simulating a first-deploy / unmigrated DB window).
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        tables_without_allowed = [
            t for name, t in Base.metadata.tables.items()
            if name != "allowed_emails"
        ]

        def _create(sync_conn):
            Base.metadata.create_all(sync_conn, tables=tables_without_allowed)

        async with engine.begin() as conn:
            await conn.run_sync(_create)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr("app.database.async_session", factory)
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@company.com")

        from app.main import _seed_admin_allowed_emails

        # Must NOT raise even though the table is missing.
        await _seed_admin_allowed_emails()

        await engine.dispose()

    async def test_seeds_when_table_present(self, session_factory, monkeypatch):
        # Happy path still works: table exists -> seed row inserted.
        monkeypatch.setattr("app.database.async_session", session_factory)
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "newseed@company.com")

        from sqlalchemy import select

        from app.models.allowed_email import AllowedEmail
        from app.main import _seed_admin_allowed_emails

        await _seed_admin_allowed_emails()

        async with session_factory() as s:
            emails = (
                await s.execute(select(AllowedEmail.email))
            ).scalars().all()
        assert "newseed@company.com" in [e.lower() for e in emails]


# --------------------------------------------------------------------------- #
# Lifespan prod-secrets gate (only when /run/secrets exists)
# --------------------------------------------------------------------------- #


class TestLifespanProdGate:
    async def test_dev_no_run_secrets_skips_assert(self, monkeypatch):
        # Insecure settings + NO /run/secrets => must NOT raise.
        monkeypatch.setattr("app.main.prod_secrets_dir_exists", lambda: False)
        monkeypatch.setattr("app.main._seed_admin_allowed_emails", _async_noop)
        monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-change-me")
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")

        from app.main import lifespan

        async with lifespan(object()):  # _app arg unused by lifespan
            pass  # reached => assertion was skipped

    async def test_prod_with_insecure_secret_raises(self, monkeypatch):
        # Insecure settings + /run/secrets exists => MUST raise before serving.
        monkeypatch.setattr("app.main.prod_secrets_dir_exists", lambda: True)
        monkeypatch.setattr("app.main._seed_admin_allowed_emails", _async_noop)
        monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-change-me")
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")

        from app.main import lifespan

        with pytest.raises(RuntimeError):
            async with lifespan(object()):
                pass

    async def test_prod_with_secure_secrets_proceeds(self, monkeypatch):
        # Secure settings + /run/secrets exists => proceeds normally.
        monkeypatch.setattr("app.main.prod_secrets_dir_exists", lambda: True)
        monkeypatch.setattr("app.main._seed_admin_allowed_emails", _async_noop)
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
        monkeypatch.setattr(settings, "JWT_SECRET", "a-real-secret")
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "GOCSPX-real")
        monkeypatch.setattr(settings, "JIRA_API_TOKEN", "real-token")
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")

        from app.main import lifespan

        async with lifespan(object()):
            pass  # reached => assertion passed
