"""Tests for the JIRA task cache upsert and serializer (REQ-SYNC-02, REQ-SYNC-03).

Patches `app.routers.jira.async_session` so the router uses the in-memory
SQLite engine from the conftest fixtures, and `get_current_user` so we don't
need a real JWT.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models.task import Task
from app.routers import jira as jira_router
from app.services.jira_client import (
    JiraAuthError,
    JiraError,
    JiraNoDoneTransitionError,
    JiraRateLimitError,
)


def _task_data(
    key: str = "PROJ-1",
    created: str = "2024-01-15T10:00:00.000+0000",
    duedate: str | None = "2024-07-01",
    description: str | None = "<p>Rendered description</p>",
) -> dict:
    """Shape matching what JiraClient._normalize_tasks() returns."""
    return {
        "jira_key": key,
        "summary": f"Task {key}",
        "status": "To Do",
        "status_category": "new",
        "priority": "Medium",
        "project_key": "PROJ",
        "project_name": "Project Alpha",
        "updated": "2024-06-01T12:00:00.000+0000",
        "created": created,
        "duedate": duedate,
        "description": description,
    }


def _make_fake_user():
    """A lightweight stand-in for the User dependency (only .id and .email are read)."""
    class _FakeUser:
        id = "user-1"
        email = "dev@example.com"
    return _FakeUser()


@pytest.fixture
def patched_jira(monkeypatch, session_factory):
    """Patch the router to use the in-memory session factory and a fake user."""
    monkeypatch.setattr(jira_router, "async_session", session_factory)
    monkeypatch.setattr(jira_router, "get_current_user", lambda: _make_fake_user())
    # Bypass JIRA-configuration guard in _get_jira_client.
    monkeypatch.setattr(jira_router.settings, "JIRA_EMAIL", "dev@example.com", raising=False)
    monkeypatch.setattr(jira_router.settings, "JIRA_API_TOKEN", "tok", raising=False)
    monkeypatch.setattr(jira_router.settings, "JIRA_DOMAIN", "example.atlassian.net", raising=False)
    # Avoid real HTTP: the router calls client.get_assigned_tasks once on cache miss.
    fake_client = AsyncMock()
    fake_client.get_assigned_tasks = AsyncMock(return_value=[])
    monkeypatch.setattr(jira_router, "_get_jira_client", lambda: fake_client)
    return fake_client


class TestUpsertWritesCreated:
    """REQ-SYNC-02 scenarios 1+2: insert and update both persist `created`."""

    async def test_insert_path_writes_created(self, patched_jira, db_session):
        # Scenario 1: fresh issue inserted with created = T.
        patched_jira.get_assigned_tasks.return_value = [_task_data(created="2024-01-15T10:00:00.000+0000")]

        await jira_router.get_jira_tasks(refresh=True, user=_make_fake_user())

        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.jira_key == "PROJ-1"))
        task = result.scalar_one()
        assert task.created == "2024-01-15T10:00:00.000+0000"

    async def test_update_path_sets_created_on_null_row(self, patched_jira, db_session):
        # Scenario 2: existing cached row with created=NULL, refreshed from JIRA with created=T.
        pre_existing = Task(
            id="pre-1",
            user_id="user-1",
            jira_key="PROJ-1",
            summary="old summary",
            status="To Do",
            status_category="new",
            project_key="PROJ",
            project_name="Project Alpha",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            created=None,
        )
        db_session.add(pre_existing)
        await db_session.commit()

        patched_jira.get_assigned_tasks.return_value = [_task_data(created="2024-02-20T09:00:00.000+0000")]

        await jira_router.get_jira_tasks(refresh=True, user=_make_fake_user())

        await db_session.refresh(pre_existing)
        assert pre_existing.created == "2024-02-20T09:00:00.000+0000"


class TestTaskToDictSerializesCreated:
    """REQ-SYNC-03: serializer emits created (valued and null)."""

    def test_serializes_created_valued(self):
        task = Task(
            id="t1",
            user_id="user-1",
            jira_key="PROJ-1",
            summary="x",
            status="To Do",
            status_category="new",
            fetched_at="2024-06-01T12:00:00.000+00:00",
            created="2024-01-15T10:00:00.000+0000",
        )

        out = jira_router._task_to_dict(task)

        assert out["created"] == "2024-01-15T10:00:00.000+0000"

    def test_serializes_created_null(self):
        # Triangulation: un-backfilled row serializes created as None.
        task = Task(
            id="t2",
            user_id="user-1",
            jira_key="PROJ-2",
            summary="y",
            status="To Do",
            status_category="new",
            fetched_at="2024-06-01T12:00:00.000+00:00",
            created=None,
        )

        out = jira_router._task_to_dict(task)

        assert out["created"] is None


class TestUpsertWritesDuedateAndDescription:
    """Upsert INSERT and UPDATE paths both persist duedate + description."""

    async def test_insert_path_writes_duedate_and_description(self, patched_jira, db_session):
        patched_jira.get_assigned_tasks.return_value = [
            _task_data(
                duedate="2024-07-01",
                description="<p>First desc</p>",
            )
        ]

        await jira_router.get_jira_tasks(refresh=True, user=_make_fake_user())

        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.jira_key == "PROJ-1"))
        task = result.scalar_one()
        assert task.duedate == "2024-07-01"
        assert task.description == "<p>First desc</p>"

    async def test_update_path_sets_duedate_and_description_on_null_row(
        self, patched_jira, db_session
    ):
        pre_existing = Task(
            id="pre-1",
            user_id="user-1",
            jira_key="PROJ-1",
            summary="old summary",
            status="To Do",
            status_category="new",
            project_key="PROJ",
            project_name="Project Alpha",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            created=None,
            duedate=None,
            description=None,
        )
        db_session.add(pre_existing)
        await db_session.commit()

        patched_jira.get_assigned_tasks.return_value = [
            _task_data(
                duedate="2024-12-31",
                description="<p>Refreshed</p>",
            )
        ]

        await jira_router.get_jira_tasks(refresh=True, user=_make_fake_user())

        await db_session.refresh(pre_existing)
        assert pre_existing.duedate == "2024-12-31"
        assert pre_existing.description == "<p>Refreshed</p>"


class TestTaskToDictSerializesDuedateAndDescription:
    """Serializer emits duedate + description (valued and null)."""

    def test_serializes_duedate_and_description_valued(self):
        task = Task(
            id="t1",
            user_id="user-1",
            jira_key="PROJ-1",
            summary="x",
            status="To Do",
            status_category="new",
            fetched_at="2024-06-01T12:00:00.000+00:00",
            created="2024-01-15T10:00:00.000+0000",
            duedate="2024-07-01",
            description="<p>Body</p>",
        )

        out = jira_router._task_to_dict(task)

        assert out["duedate"] == "2024-07-01"
        assert out["description"] == "<p>Body</p>"

    def test_serializes_duedate_and_description_null(self):
        task = Task(
            id="t2",
            user_id="user-1",
            jira_key="PROJ-2",
            summary="y",
            status="To Do",
            status_category="new",
            fetched_at="2024-06-01T12:00:00.000+00:00",
            created=None,
            duedate=None,
            description=None,
        )

        out = jira_router._task_to_dict(task)

        assert out["duedate"] is None
        assert out["description"] is None


def _seed_task(
    db_session,
    *,
    key: str = "PROJ-1",
    user_id: str = "user-1",
    status: str = "In Progress",
    category: str = "indeterminate",
) -> Task:
    """Insert and commit a cached Task row for the close-endpoint tests."""
    task = Task(
        id=f"seed-{key}",
        user_id=user_id,
        jira_key=key,
        summary=f"Task {key}",
        status=status,
        status_category=category,
        project_key="PROJ",
        project_name="Project Alpha",
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(task)
    return task


class TestCloseTask:
    """POST /api/jira/tasks/{task_key}/close — transition a task to Done.

    Contract:
    - 200 on success: cached row updated (status + status_category='done'),
      returns {"jira_key", "status"}.
    - 404 when the task is not owned by the caller (no row for user_id).
    - 409 JiraNoDoneTransitionError, 500 JiraAuthError, 503 rate limit, 502 generic.
    """

    async def test_close_updates_cached_row_and_returns_status(self, patched_jira, db_session):
        task = _seed_task(db_session)
        await db_session.commit()
        patched_jira.transition_to_done = AsyncMock(return_value="Done")

        result = await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert result == {"jira_key": "PROJ-1", "status": "Done"}
        patched_jira.transition_to_done.assert_awaited_once_with("PROJ-1")
        await db_session.refresh(task)
        assert task.status == "Done"
        assert task.status_category == "done"

    async def test_close_returns_404_when_task_not_owned_by_user(self, patched_jira, db_session):
        _seed_task(db_session, user_id="user-other")
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert exc.value.status_code == 404
        patched_jira.transition_to_done.assert_not_called()

    async def test_close_returns_409_when_no_done_transition(self, patched_jira, db_session):
        _seed_task(db_session)
        await db_session.commit()
        patched_jira.transition_to_done = AsyncMock(
            side_effect=JiraNoDoneTransitionError("no path")
        )

        with pytest.raises(HTTPException) as exc:
            await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert exc.value.status_code == 409

    async def test_close_returns_500_on_jira_auth_error(self, patched_jira, db_session):
        _seed_task(db_session)
        await db_session.commit()
        patched_jira.transition_to_done = AsyncMock(side_effect=JiraAuthError("bad creds"))

        with pytest.raises(HTTPException) as exc:
            await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert exc.value.status_code == 500

    async def test_close_returns_503_on_rate_limit(self, patched_jira, db_session):
        _seed_task(db_session)
        await db_session.commit()
        patched_jira.transition_to_done = AsyncMock(side_effect=JiraRateLimitError("slow"))

        with pytest.raises(HTTPException) as exc:
            await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert exc.value.status_code == 503

    async def test_close_returns_502_on_generic_jira_error(self, patched_jira, db_session):
        _seed_task(db_session)
        await db_session.commit()
        patched_jira.transition_to_done = AsyncMock(side_effect=JiraError("boom"))

        with pytest.raises(HTTPException) as exc:
            await jira_router.close_task("PROJ-1", user=_make_fake_user())

        assert exc.value.status_code == 502
