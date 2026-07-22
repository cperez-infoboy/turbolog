"""Pytest fixtures for Turbolog backend tests.

Minimal async in-memory SQLite harness. Each test gets a fresh schema created
from the SQLAlchemy models (no Alembic needed at test time) and a session
factory bound to the in-memory engine.

Additional fixtures (app/client/jira_fake) support the "Cerrar día" feature
tests in test_status_finalize.py: they wire the status router to the in-memory
DB, override get_current_user, and inject a configurable JIRA client fake.
"""
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
# Import models so Base.metadata knows about every table.
from app.models import AllowedEmail, StatusReport, Task, User  # noqa: F401
# Ensure DailyClosure registers with metadata (imported for side effect).
from app.models.daily_closure import DailyClosure  # noqa: F401


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


# --------------------------------------------------------------------------- #
# Fixtures for the "Cerrar día" feature (status router black-box tests)
# --------------------------------------------------------------------------- #


class _JiraFake:
    """Configurable stand-in for the JiraClient used by the status router.

    Attributes:
        add_comment_side_effect: None -> returns add_comment_return_id;
            otherwise a callable(issue_key, text) -> id, or an Exception to
            raise. When a callable raises, that counts as a per-report failure.
        add_comment_return_id: comment id returned on the default success path.
        call_log: list of (issue_key, text) tuples for invocation assertions.
    """

    def __init__(self) -> None:
        self.add_comment_return_id: str = "fake-comment-id"
        self._per_key: dict[str, object] = {}
        self._default_side_effect: object = None
        self.call_log: list[tuple[str, str]] = []
        # transition_to_done support (deferred-close feature).
        self.transition_return_name: str = "Done"
        self._transition_per_key: dict[str, object] = {}
        self._transition_default_side_effect: object = None
        self.transition_call_log: list[str] = []

    def set_default_side_effect(self, se) -> None:
        """Set the side effect applied when no per-key override matches."""
        self._default_side_effect = se

    def set_per_key(self, issue_key: str, se) -> None:
        """Override add_comment behavior for a single issue key only."""
        self._per_key[issue_key] = se

    async def add_comment(self, issue_key: str, comment_text: str) -> str:
        self.call_log.append((issue_key, comment_text))
        se = self._per_key.get(issue_key, self._default_side_effect)
        if se is None:
            return self.add_comment_return_id
        if isinstance(se, Exception):
            raise se
        if callable(se):
            return se(issue_key, comment_text)
        return self.add_comment_return_id

    def set_transition_default_side_effect(self, se) -> None:
        """Set the side effect applied when no per-key transition override matches."""
        self._transition_default_side_effect = se

    def set_transition_per_key(self, issue_key: str, se) -> None:
        """Override transition_to_done behavior for a single issue key only."""
        self._transition_per_key[issue_key] = se

    async def transition_to_done(self, issue_key: str) -> str:
        self.transition_call_log.append(issue_key)
        se = self._transition_per_key.get(issue_key, self._transition_default_side_effect)
        if se is None:
            return self.transition_return_name
        if isinstance(se, Exception):
            raise se
        if callable(se):
            return se(issue_key)
        return self.transition_return_name


@pytest.fixture
def jira_fake() -> _JiraFake:
    """Per-test configurable JiraClient fake."""
    return _JiraFake()


@pytest_asyncio.fixture
async def test_user(session_factory):
    """A real User row inserted in the test DB; used by get_current_user override."""
    async with session_factory() as session:
        user = User(
            id="test-user-id",
            google_sub="google-sub-123",
            email="tester@example.com",
            name="Tester",
            picture=None,
        )
        session.add(user)
        await session.commit()
        return user


@pytest_asyncio.fixture
async def app(session_factory, test_user, jira_fake):
    """A FastAPI app with overrides wiring the status router to the test DB.

    The status router opens its own `async_session()` directly (not via a
    dependency), so we patch `app.routers.status.async_session` to the in-memory
    session factory. `get_current_user` is overridden via dependency_overrides so
    no JWT is needed. `get_jira_client` is overridden so tests control JIRA.
    """
    from fastapi import FastAPI

    from app.dependencies import get_current_user, get_jira_client
    from app.routers import status as status_router

    # Re-wire the status router's session factory to the in-memory engine.
    status_router.async_session = session_factory

    test_app = FastAPI()
    test_app.include_router(status_router.router)

    async def _override_user():
        async with session_factory() as s:
            result = await s.execute(select(User).where(User.id == test_user.id))
            return result.scalar_one()

    def _override_jira():
        return jira_fake

    test_app.dependency_overrides[get_current_user] = _override_user
    test_app.dependency_overrides[get_jira_client] = _override_jira

    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """httpx AsyncClient talking to the test app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
