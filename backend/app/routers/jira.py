import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.dependencies import get_current_user, get_jira_client
from app.models.daily_closure import DailyClosure
from app.models.status_report import StatusReport
from app.models.task import Task
from app.models.user import User
from app.services.jira_client import (
    JiraAuthError,
    JiraClient,
    JiraError,
    JiraRateLimitError,
    jira_base_url,
)

router = APIRouter(prefix="/api/jira", tags=["jira"])


# Backward-compat alias: the shared factory now lives in app.dependencies so it
# can be overridden via FastAPI's dependency_overrides. Kept here so existing
# callers (and tests that monkeypatch this module) keep working.
def _get_jira_client() -> JiraClient:
    """Create a JiraClient using the global admin credentials from settings."""
    return get_jira_client()


@router.get("/tasks")
async def get_jira_tasks(
    refresh: bool = False,
    user: User = Depends(get_current_user),
):
    """Fetch user's assigned JIRA tasks using the global admin token.
    Filters by user's Google email (assumed to match JIRA email).
    Uses DB cache with TTL. Query param ?refresh=true bypasses cache.
    """
    client = _get_jira_client()
    now = datetime.now(timezone.utc)

    # Check cache (unless refresh is requested)
    if not refresh:
        async with async_session() as session:
            ttl_threshold = (now - timedelta(seconds=settings.JIRA_CACHE_TTL)).isoformat()
            result = await session.execute(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.fetched_at >= ttl_threshold,
                )
            )
            cached_tasks = result.scalars().all()

            if cached_tasks:
                return [_task_to_dict(t) for t in cached_tasks]

    # Cache miss or refresh requested: fetch from JIRA
    try:
        jira_tasks = await client.get_assigned_tasks(assignee_email=user.email)
    except JiraAuthError:
        raise HTTPException(500, "JIRA server credentials are invalid")
    except JiraRateLimitError:
        # Try to serve stale cache on rate limit
        async with async_session() as session:
            result = await session.execute(
                select(Task).where(Task.user_id == user.id)
            )
            stale = result.scalars().all()
            if stale:
                return {"tasks": [_task_to_dict(t) for t in stale], "stale": True}
        raise HTTPException(503, "JIRA rate limit exceeded, try again later")
    except JiraError as e:
        # Try to serve stale cache on error
        async with async_session() as session:
            result = await session.execute(
                select(Task).where(Task.user_id == user.id)
            )
            stale = result.scalars().all()
            if stale:
                return {"tasks": [_task_to_dict(t) for t in stale], "stale": True}
        raise HTTPException(502, str(e))

    # Upsert into cache
    fetched_at = now.isoformat()
    async with async_session() as session:
        for task_data in jira_tasks:
            result = await session.execute(
                select(Task).where(
                    Task.user_id == user.id,
                    Task.jira_key == task_data["jira_key"],
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.summary = task_data["summary"]
                existing.status = task_data["status"]
                existing.status_category = task_data.get("status_category")
                existing.priority = task_data.get("priority")
                existing.project_key = task_data.get("project_key")
                existing.project_name = task_data.get("project_name")
                existing.created = task_data.get("created")
                existing.duedate = task_data.get("duedate")
                existing.description = task_data.get("description")
                existing.comments = task_data.get("comments")
                existing.fetched_at = fetched_at
            else:
                task = Task(
                    id=secrets.token_hex(16),
                    user_id=user.id,
                    jira_key=task_data["jira_key"],
                    summary=task_data["summary"],
                    status=task_data["status"],
                    status_category=task_data.get("status_category"),
                    priority=task_data.get("priority"),
                    project_key=task_data.get("project_key"),
                    project_name=task_data.get("project_name"),
                    created=task_data.get("created"),
                    duedate=task_data.get("duedate"),
                    description=task_data.get("description"),
                    comments=task_data.get("comments"),
                    fetched_at=fetched_at,
                )
                session.add(task)

        await session.commit()

    return jira_tasks


@router.post("/tasks/{task_key}/close")
async def close_task(
    task_key: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Mark a task's status report as pending-close for the given date.

    Deferred-close flow: instead of transitioning JIRA immediately, this stores
    a pending-close intention on the StatusReport. The actual transition runs
    when the user finalizes the day (POST /api/status/finalize), alongside
    comment posting.
    """
    raw_date = body.get("date") if isinstance(body, dict) else None
    if not isinstance(raw_date, str) or not raw_date.strip():
        raise HTTPException(400, "Fecha requerida")
    report_date = raw_date.strip()

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.user_id == user.id, Task.jira_key == task_key)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(404, "Tarea no encontrada")

        closure_result = await session.execute(
            select(DailyClosure).where(
                DailyClosure.user_id == user.id,
                DailyClosure.report_date == report_date,
            )
        )
        if closure_result.scalar_one_or_none() is not None:
            raise HTTPException(409, "El día ya está cerrado")

        report_result = await session.execute(
            select(StatusReport).where(
                StatusReport.user_id == user.id,
                StatusReport.task_key == task_key,
                StatusReport.report_date == report_date,
            )
        )
        report = report_result.scalar_one_or_none()
        if report is None or not report.content.strip():
            raise HTTPException(422, "Debes ingresar un status antes de cerrar la tarea.")

        report.pending_close = True
        await session.commit()

    return {"task_key": task_key, "pending_close": True}


@router.delete("/tasks/{task_key}/close")
async def cancel_close_task(
    task_key: str,
    date: str,
    user: User = Depends(get_current_user),
):
    """Clear the pending-close intention for a task on the given date."""
    if not date.strip():
        raise HTTPException(400, "Fecha requerida")
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.user_id == user.id, Task.jira_key == task_key)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(404, "Tarea no encontrada")

        closure_result = await session.execute(
            select(DailyClosure).where(
                DailyClosure.user_id == user.id,
                DailyClosure.report_date == date,
            )
        )
        if closure_result.scalar_one_or_none() is not None:
            raise HTTPException(409, "El día ya está cerrado")

        report_result = await session.execute(
            select(StatusReport).where(
                StatusReport.user_id == user.id,
                StatusReport.task_key == task_key,
                StatusReport.report_date == date,
            )
        )
        report = report_result.scalar_one_or_none()
        if report is not None:
            report.pending_close = False
            await session.commit()

    return {"task_key": task_key, "pending_close": False}


def _task_to_dict(task: Task) -> dict:
    browse_url = (
        f"{jira_base_url(settings.JIRA_DOMAIN)}/browse/{task.jira_key}"
        if settings.JIRA_DOMAIN
        else None
    )
    return {
        "jira_key": task.jira_key,
        "browse_url": browse_url,
        "summary": task.summary,
        "status": task.status,
        "status_category": task.status_category,
        "priority": task.priority,
        "project_key": task.project_key,
        "project_name": task.project_name,
        "updated": task.fetched_at,
        "created": task.created,
        "duedate": task.duedate,
        "description": task.description,
    }
