"""Tests for /api/health/ready — schema sanity probe (NOT bare connectivity).

Contract:
- 200 when the ``alembic_version`` table exists (migrations ran).
- 503 when it is absent (unmigrated / empty DB).

The 503 path is the load-bearing case: the conftest harness creates every
SQLAlchemy model table via ``Base.metadata.create_all`` but it does NOT create
``alembic_version`` (that table is Alembic-managed, not a model). So a probe of
``SELECT 1 FROM alembic_version`` against the fully-tabled in-memory DB still
fails, proving the endpoint is a SCHEMA check and not a bare ``SELECT 1``
(which would return 200 against an unmigrated DB while real requests 500).
"""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def alembic_engine():
    """In-memory engine that has ONLY the alembic_version table + one row."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('fakehead')")
        )
    yield engine
    await engine.dispose()


def _client():
    """httpx client bound to the real app via ASGITransport (no lifespan run)."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


class TestHealthReady:
    async def test_503_when_alembic_version_table_absent(self, session_factory, monkeypatch):
        # session_factory has every model table BUT no alembic_version table.
        monkeypatch.setattr("app.database.async_session", session_factory)

        async with _client() as c:
            resp = await c.get("/api/health/ready")

        assert resp.status_code == 503, resp.text

    async def test_200_when_alembic_version_table_exists(self, alembic_engine, monkeypatch):
        factory = async_sessionmaker(alembic_engine, expire_on_commit=False)
        monkeypatch.setattr("app.database.async_session", factory)

        async with _client() as c:
            resp = await c.get("/api/health/ready")

        assert resp.status_code == 200, resp.text

    async def test_existing_health_still_ok(self, session_factory, monkeypatch):
        # The liveness probe /api/health must remain untouched.
        monkeypatch.setattr("app.database.async_session", session_factory)

        async with _client() as c:
            resp = await c.get("/api/health")

        assert resp.status_code == 200
