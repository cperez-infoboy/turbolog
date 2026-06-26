"""Tests for the Telegram router (RED phase).

Endpoints:
- GET  /api/telegram/status  → {linked, chat_id}
- POST /api/telegram/link    → {code, bot_username}
- DELETE /api/telegram/link  → {status}
"""
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.dependencies import get_current_user
from app.models.user import User


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def test_user(session_factory):
    async with session_factory() as session:
        user = User(
            id="test-user-id",
            google_sub="google-sub-123",
            email="tester@example.com",
            name="Tester",
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def app(session_factory, test_user):
    from fastapi import FastAPI

    from app.routers import telegram as telegram_router
    from app.services.telegram_verification import VerificationStore

    telegram_router.async_session = session_factory

    # Create a shared verification store for tests.
    store = VerificationStore(ttl_seconds=300)
    telegram_router._verification_store = store

    test_app = FastAPI()
    test_app.include_router(telegram_router.router)

    async def _override_user():
        async with session_factory() as s:
            result = await s.execute(select(User).where(User.id == test_user.id))
            return result.scalar_one()

    test_app.dependency_overrides[get_current_user] = _override_user
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- #
# GET /api/telegram/status
# --------------------------------------------------------------------------- #


class TestTelegramStatus:
    async def test_unlinked_user(self, client):
        resp = await client.get("/api/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["linked"] is False
        assert data["chat_id"] is None

    async def test_linked_user(self, client, session_factory, test_user):
        async with session_factory() as session:
            user = await session.get(User, test_user.id)
            user.telegram_chat_id = "12345"
            await session.commit()

        resp = await client.get("/api/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["linked"] is True
        assert data["chat_id"] == "12345"


# --------------------------------------------------------------------------- #
# POST /api/telegram/link
# --------------------------------------------------------------------------- #


class TestTelegramLink:
    async def test_generates_code(self, client):
        resp = await client.post("/api/telegram/link")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["code"]) == 6
        assert data["code"].isdigit()
        assert "bot_username" in data

    async def test_replaces_previous_code(self, client):
        r1 = await client.post("/api/telegram/link")
        r2 = await client.post("/api/telegram/link")
        # Both succeed, second replaces first.
        assert r1.status_code == 200
        assert r2.status_code == 200


# --------------------------------------------------------------------------- #
# DELETE /api/telegram/link
# --------------------------------------------------------------------------- #


class TestTelegramUnlink:
    async def test_unlinks_user(self, client, session_factory, test_user):
        # First link the user.
        async with session_factory() as session:
            user = await session.get(User, test_user.id)
            user.telegram_chat_id = "12345"
            await session.commit()

        resp = await client.delete("/api/telegram/link")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unlinked"

        # Verify DB.
        async with session_factory() as session:
            user = await session.get(User, test_user.id)
            assert user.telegram_chat_id is None

    async def test_unlink_when_not_linked(self, client):
        resp = await client.delete("/api/telegram/link")
        assert resp.status_code == 200
