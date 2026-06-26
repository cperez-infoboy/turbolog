"""Telegram linking router.

Endpoints for users to link/unlink their Telegram account for notifications.
Uses a shared :class:`VerificationStore` (injected at app startup).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.dependencies import get_current_user
from app.models.user import User
from app.services.telegram_verification import VerificationStore

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

# Module-level store, replaced at app startup if the bot is configured.
_verification_store: VerificationStore | None = None


def _get_verification_store() -> VerificationStore:
    """Return the module-level verification store, or create a default one."""
    global _verification_store
    if _verification_store is None:
        _verification_store = VerificationStore()
    return _verification_store


def _set_verification_store(store: VerificationStore) -> None:
    """Replace the module-level store (called from app lifespan)."""
    global _verification_store
    _verification_store = store


@router.get("/status")
async def telegram_status(user: User = Depends(get_current_user)):
    """Return the user's Telegram linking status."""
    return {
        "linked": user.telegram_chat_id is not None,
        "chat_id": user.telegram_chat_id,
    }


@router.post("/link")
async def telegram_link(user: User = Depends(get_current_user)):
    """Generate a verification code for Telegram linking.

    The user sends this code to the Telegram bot to complete the link.
    Any previous (unverified) code for this user is replaced.
    """
    store = _get_verification_store()
    code = store.create_code(user.id)

    bot_username = settings.TELEGRAM_BOT_USERNAME

    return {
        "code": code,
        "bot_username": bot_username,
        "expires_in": settings.TELEGRAM_CODE_TTL_SECONDS,
    }


@router.delete("/link")
async def telegram_unlink(
    user: User = Depends(get_current_user),
):
    """Unlink the user's Telegram account."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user.id)
        )
        db_user = result.scalar_one_or_none()
        if db_user is not None:
            db_user.telegram_chat_id = None
            await session.commit()

    return {"status": "unlinked"}
