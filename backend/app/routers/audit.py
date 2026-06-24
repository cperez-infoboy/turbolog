"""Admin audit router: user management, monthly audit report, and manual job trigger.

All endpoints require ``require_admin`` (DB flag OR immutable ADMIN_EMAILS seed).
The router opens its own ``async_session()`` per the repo pattern, so tests patch
``audit_router.async_session`` to rebind it to the in-memory engine.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.database import async_session
from app.dependencies import _admin_seed, get_notifier, is_super_admin, require_admin
from app.jobs.reminder import run_reminder_job
from app.models.allowed_email import AllowedEmail
from app.models.user import User
from app.services.audit_service import compute_audit_for_all_users

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _reflect_admin(user: User) -> bool:
    """The effective admin status shown to the UI: DB flag OR seed membership."""
    return bool(user.is_admin or is_super_admin(user))


def _user_shape(user: User) -> dict:
    """Serialize a user row into the admin-listing shape."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": _reflect_admin(user),
        "is_audited": bool(user.is_audited),
        "is_seed": is_super_admin(user),
    }


@router.get("/users")
async def list_users(_admin: User = Depends(require_admin)):
    """List every user with their admin/audited flags (for the admin panel)."""
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.email))
        users = result.scalars().all()
    return [_user_shape(u) for u in users]


@router.patch("/users/{user_id}")
async def update_user_flags(
    user_id: str,
    body: dict,
    _admin: User = Depends(require_admin),
):
    """Update is_admin / is_audited flags for a user.

    Rules:
    - Super-admin seed users are immutable: ``is_admin=False`` is ignored so a
      seed user can never be demoted (returns 200 with admin still True).
    - Anti-lockout: demoting the last non-seed DB admin to is_admin=False is
      rejected with 409 (there must always be at least one manageable admin).
    """
    new_is_admin = body.get("is_admin")
    new_is_audited = body.get("is_audited")

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(404, "User not found")

        seed = _admin_seed()
        is_seed = user.email.strip().lower() in seed

        if new_is_audited is not None:
            user.is_audited = bool(new_is_audited)

        if new_is_admin is not None:
            if is_seed:
                # Seed is immutable: keep admin regardless of the request.
                user.is_admin = True
            elif new_is_admin is False and user.is_admin:
                # Anti-lockout: only matters on an actual demotion (user is
                # currently admin). Count OTHER non-seed admins (exclude self).
                other_admins = (
                    await session.execute(
                        select(func.count())
                        .select_from(User)
                        .where(
                            User.is_admin.is_(True),
                            User.id != user.id,
                            ~func.lower(User.email).in_(list(seed)) if seed else True,
                        )
                    )
                ).scalar_one()
                # No other non-seed admin remains -> refuse.
                if other_admins == 0:
                    raise HTTPException(409, "Cannot remove the last admin")
                user.is_admin = False
            else:
                user.is_admin = bool(new_is_admin)

        await session.commit()
        await session.refresh(user)
        return _user_shape(user)


@router.get("/monthly")
async def monthly_report(
    year: int,
    month: int,
    _admin: User = Depends(require_admin),
):
    """Monthly audit report for all is_audited=True users.

    Passes the session FACTORY to the service (it opens its own session).
    """
    if not (1 <= month <= 12):
        raise HTTPException(400, "month must be 1-12")
    if year < 2000 or year > 2100:
        raise HTTPException(400, "year out of range")

    entries = await compute_audit_for_all_users(async_session, year, month)
    return entries


@router.post("/run-reminders")
async def trigger_reminders(
    _admin: User = Depends(require_admin),
    notifier=Depends(get_notifier),
):
    """Manually trigger the reminder job (admin only)."""
    await run_reminder_job(notifier)
    return {"status": "done"}


# --------------------------------------------------------------------------- #
# Allow-list (allowed_emails) management
# --------------------------------------------------------------------------- #


def _allowed_shape(row: AllowedEmail) -> dict:
    """Serialize an AllowedEmail row into the admin-listing shape."""
    return {
        "email": row.email,
        "added_by": row.added_by,
        "created_at": row.created_at,
        "is_seed": row.email.strip().lower() in _admin_seed(),
    }


@router.get("/allowed-emails")
async def list_allowed_emails(_admin: User = Depends(require_admin)):
    """List every authorized email, ordered by email."""
    async with async_session() as session:
        result = await session.execute(
            select(AllowedEmail).order_by(AllowedEmail.email)
        )
        rows = result.scalars().all()
    return [_allowed_shape(r) for r in rows]


@router.post("/allowed-emails")
async def add_allowed_email(
    body: dict,
    admin: User = Depends(require_admin),
):
    """Authorize an email. Idempotent: if it already exists, return it.

    The email is normalized to lowercase (trimmed). ``added_by`` is the admin
    who performed the add. Rejects empty/whitespace emails with 400.
    """
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "email is required")

    async with async_session() as session:
        existing = await session.scalar(
            select(AllowedEmail).where(AllowedEmail.email == email)
        )
        if existing is not None:
            return _allowed_shape(existing)

        row = AllowedEmail(email=email, added_by=admin.id)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _allowed_shape(row)


@router.delete("/allowed-emails/{email}")
async def delete_allowed_email(
    email: str,
    _admin: User = Depends(require_admin),
):
    """Revoke an email. 404 if not found. Matches by normalized email."""
    email_n = email.strip().lower()
    async with async_session() as session:
        row = await session.scalar(
            select(AllowedEmail).where(AllowedEmail.email == email_n)
        )
        if row is None:
            raise HTTPException(404, "email not found")
        await session.delete(row)
        await session.commit()
    return {"status": "deleted"}
