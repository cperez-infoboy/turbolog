import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from jose import jwt
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# --- Helpers ----------------------------------------------------------------


def _make_jwt(user_id: str, email: str, name: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=settings.APP_URL.startswith("https"),
        samesite="lax",
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key="auth_token", path="/")


# --- Endpoints --------------------------------------------------------------


@router.get("/google/login")
async def google_login():
    """Redirect browser to Google's OAuth consent screen."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{settings.APP_URL}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return Response(status_code=302, headers={"Location": url})


@router.get("/google/callback")
async def google_callback(code: str):
    """Exchange authorization code for access token, fetch user info.
    Existing user: set JWT cookie, redirect to /.
    New user: redirect to /register?state=base64(google_data).
    """
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{settings.APP_URL}/api/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        google_user = user_resp.json()

    google_sub = google_user["id"]
    email = google_user["email"]
    name = google_user["name"]
    picture = google_user.get("picture")

    # Check if user already exists
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.google_sub == google_sub)
        )
        existing_user = result.scalar_one_or_none()

    if existing_user:
        token = _make_jwt(existing_user.id, existing_user.email, existing_user.name)
        response = Response(
            status_code=302,
            headers={"Location": f"{settings.APP_URL}/"},
        )
        _set_auth_cookie(response, token)
        return response

    # New user: redirect to registration page with Google profile data
    state_data = {
        "google_sub": google_sub,
        "email": email,
        "name": name,
        "picture": picture,
    }
    state_encoded = base64.urlsafe_b64encode(
        json.dumps(state_data).encode()
    ).decode()

    response = Response(
        status_code=302,
        headers={"Location": f"{settings.APP_URL}/register?state={state_encoded}"},
    )
    return response


@router.post("/register")
async def register(body: dict):
    """Create user account from Google profile data and set JWT cookie.
    No profile name required -- uses Google name directly.
    """
    google_sub = body.get("google_sub", "").strip()
    email = body.get("email", "").strip()
    name = body.get("name", "").strip()
    picture = body.get("picture")

    if not google_sub or not email or not name:
        raise HTTPException(400, "Missing required fields")

    async with async_session() as session:
        # Check if google_sub already registered (shouldn't happen, but guard)
        existing = await session.execute(
            select(User).where(User.google_sub == google_sub)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "User already registered")

        user_id = secrets.token_hex(16)
        user = User(
            id=user_id,
            google_sub=google_sub,
            email=email,
            name=name,
            picture=picture,
        )
        session.add(user)
        await session.commit()

    token = _make_jwt(user.id, user.email, user.name)
    response = Response(
        status_code=200,
        content=json.dumps({"user_id": user.id}),
        media_type="application/json",
    )
    _set_auth_cookie(response, token)
    return response


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """Return current user info. Validates JWT cookie via dependency."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "created_at": user.created_at,
    }


@router.post("/logout")
async def logout():
    """Clear the JWT cookie."""
    response = Response(status_code=200)
    _clear_auth_cookie(response)
    return response
