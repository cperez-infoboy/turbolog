"""Pytest fixtures for Turbolog backend tests.

Minimal async in-memory SQLite harness. Each test gets a fresh schema created
from the SQLAlchemy models (no Alembic needed at test time) and a session
factory bound to the in-memory engine.
"""
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Import models so Base.metadata knows about every table.
from app.models import StatusReport, Task, User  # noqa: F401


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine with all tables created per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator:
    """Convenience async session for tests that operate directly on the DB."""
    async with session_factory() as session:
        yield session
