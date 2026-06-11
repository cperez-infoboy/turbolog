from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.user import User


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async generator that yields a database session."""
    async with async_session() as session:
        yield session


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
