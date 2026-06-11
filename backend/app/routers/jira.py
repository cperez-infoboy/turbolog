import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.dependencies import get_current_user
from app.models.jira_connection import JiraConnection
from app.models.task import Task
from app.models.user import User
from app.services import encryption
from app.services.jira_client import JiraAuthError, JiraClient, JiraError, JiraRateLimitError

router = APIRouter(prefix="/api/jira", tags=["jira"])


@router.post("/connect")
async def connect_jira(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Validate JIRA credentials and store encrypted connection.
    Upserts: replaces existing connection if one exists.
    """
    jira_email = body.get("jira_email", "").strip()
    api_token = body.get("api_token", "").strip()
    jira_domain = body.get("jira_domain", "").strip()

    if not jira_email or not api_token or not jira_domain:
        raise HTTPException(400, "jira_email, api_token, and jira_domain are required")

    # Validate credentials against JIRA API
    client = JiraClient(jira_domain, jira_email, api_token)
    try:
        myself = await client.get_myself()
    except JiraAuthError:
        raise HTTPException(401, "Invalid JIRA credentials")
    except JiraRateLimitError:
        raise HTTPException(503, "JIRA rate limit exceeded, try again later")
    except JiraError as e:
        raise HTTPException(502, str(e))

    display_name = myself.get("displayName", jira_email)
    encrypted_token = encryption.encrypt(api_token)
    now = datetime.now(timezone.utc).isoformat()

    async with async_session() as session:
        # Check for existing connection (upsert)
        result = await session.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.jira_email = jira_email
            existing.jira_api_token_encrypted = encrypted_token
            existing.jira_domain = jira_domain
            existing.last_verified = now
        else:
            connection = JiraConnection(
                id=secrets.token_hex(16),
                user_id=user.id,
                jira_email=jira_email,
                jira_api_token_encrypted=encrypted_token,
                jira_domain=jira_domain,
                last_verified=now,
            )
            session.add(connection)

        await session.commit()

    return {
        "connected": True,
        "email": jira_email,
        "domain": jira_domain,
        "display_name": display_name,
    }


@router.delete("/disconnect")
async def disconnect_jira(user: User = Depends(get_current_user)):
    """Remove the user's JIRA connection and encrypted token."""
    async with async_session() as session:
        result = await session.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()

        if connection:
            await session.delete(connection)
            await session.commit()

    return {"status": "disconnected"}


@router.get("/connection")
async def get_connection_status(user: User = Depends(get_current_user)):
    """Return JIRA connection metadata. Never returns the token."""
    async with async_session() as session:
        result = await session.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()

    if not connection:
        raise HTTPException(404, "No JIRA connection configured")

    return {
        "connected": True,
        "email": connection.jira_email,
        "domain": connection.jira_domain,
        "last_verified": connection.last_verified,
    }


@router.get("/tasks")
async def get_jira_tasks(
    refresh: bool = False,
    user: User = Depends(get_current_user),
):
    """Fetch user's assigned JIRA tasks. Uses DB cache with TTL.
    Query param ?refresh=true bypasses cache.
    """
    async with async_session() as session:
        # Get JIRA connection
        result = await session.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        connection = result.scalar_one_or_none()

    if not connection:
        raise HTTPException(404, "No JIRA connection configured")

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
    api_token = encryption.decrypt(connection.jira_api_token_encrypted)
    client = JiraClient(connection.jira_domain, connection.jira_email, api_token)

    try:
        jira_tasks = await client.get_assigned_tasks()
    except JiraAuthError:
        raise HTTPException(401, "JIRA credentials invalid")
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
                existing.priority = task_data.get("priority")
                existing.project_key = task_data.get("project_key")
                existing.project_name = task_data.get("project_name")
                existing.fetched_at = fetched_at
            else:
                task = Task(
                    id=secrets.token_hex(16),
                    user_id=user.id,
                    jira_key=task_data["jira_key"],
                    summary=task_data["summary"],
                    status=task_data["status"],
                    priority=task_data.get("priority"),
                    project_key=task_data.get("project_key"),
                    project_name=task_data.get("project_name"),
                    fetched_at=fetched_at,
                )
                session.add(task)

        await session.commit()

    return jira_tasks


def _task_to_dict(task: Task) -> dict:
    return {
        "jira_key": task.jira_key,
        "summary": task.summary,
        "status": task.status,
        "priority": task.priority,
        "project_key": task.project_key,
        "project_name": task.project_name,
        "updated": task.fetched_at,
    }
