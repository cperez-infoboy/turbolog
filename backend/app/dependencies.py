from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.allowed_email import AllowedEmail
from app.models.user import User
from app.services.jira_client import JiraClient
from app.services.notifier import Notifier, build_notifier


def _admin_seed() -> set[str]:
    """Super-admin emails from ``settings.ADMIN_EMAILS`` (comma-separated).

    Lower-cased and stripped. These users are auto-promoted to admin on
    registration and cannot be demoted via API (the seed is immutable).
    Shared with :func:`app.routers.auth.register` and :func:`is_super_admin`.
    """
    return {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async generator that yields a database session."""
    async with async_session() as session:
        yield session


def get_jira_client() -> JiraClient:
    """Create a JiraClient using the global admin credentials from settings.

    Raises HTTPException(500) if JIRA is not configured. Used as a FastAPI
    dependency so tests can override it via `app.dependency_overrides`.
    """
    if not settings.JIRA_EMAIL or not settings.JIRA_API_TOKEN or not settings.JIRA_DOMAIN:
        raise HTTPException(500, "JIRA is not configured on the server")
    return JiraClient(settings.JIRA_DOMAIN, settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)


async def get_current_user(request: Request) -> User:
    """FastAPI dependency: reads JWT cookie, validates it, returns User or raises 401."""
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(401, "Not authenticated")

    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == payload["sub"])
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(401, "User not found")
        return user


def is_super_admin(user: User) -> bool:
    """True if the user's email is in the immutable ``ADMIN_EMAILS`` seed."""
    return user.email.strip().lower() in _admin_seed()


async def can_login(session: AsyncSession, email: str) -> bool:
    """True if ``email`` may log in.

    Accepts the email if it is in the immutable ``ADMIN_EMAILS`` seed (bootstrap
    + safety net) OR a matching normalized row exists in ``allowed_emails``.
    Removal of a row revokes access on the next login attempt.
    """
    email_n = email.strip().lower()
    if email_n in _admin_seed():
        return True
    found = await session.scalar(
        select(AllowedEmail.id).where(AllowedEmail.email == email_n)
    )
    return found is not None


def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: allow only admins.

    A user is an admin if their DB flag ``is_admin`` is set OR they belong to
    the immutable ``ADMIN_EMAILS`` seed. Raises 403 otherwise.
    """
    if not (user.is_admin or is_super_admin(user)):
        raise HTTPException(403, "Admin only")
    return user


def get_notifier() -> Notifier:
    """FastAPI dependency: build the notifier selected by settings."""
    return build_notifier(settings)
