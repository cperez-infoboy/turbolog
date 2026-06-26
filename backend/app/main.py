import hashlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.config import settings
from app.models.allowed_email import AllowedEmail
from app.routers.auth import router as auth_router
from app.routers.audit import router as audit_router
from app.routers.jira import router as jira_router
from app.routers.status import router as status_router
from app.routers.telegram import router as telegram_router
from app.services.telegram_bot import TelegramBotService
from app.services.telegram_verification import VerificationStore

# Shared verification store (used by router and bot).
_verification = VerificationStore(ttl_seconds=settings.TELEGRAM_CODE_TTL_SECONDS)

# Inject the store into the telegram router module.
from app.routers import telegram as _tg_router_module
_tg_router_module._verification_store = _verification

_bot_service: TelegramBotService | None = None


async def _seed_admin_allowed_emails() -> None:
    """Ensure every ADMIN_EMAILS entry exists in allowed_emails.

    On a fresh database the backfill migration has no users to copy from, so
    seed emails are absent from the allow-list.  This runs once at startup and
    is idempotent (skips existing rows).
    """
    seed = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
    if not seed:
        return
    from app.database import async_session as _session_factory

    async with _session_factory() as session:
        existing = (
            await session.execute(
                select(AllowedEmail.email).where(
                    AllowedEmail.email.in_(list(seed))
                )
            )
        ).scalars().all()
        existing_set = {e.lower() for e in existing}
        now = datetime.now(timezone.utc).isoformat()
        for email in seed - existing_set:
            session.add(AllowedEmail(
                id=hashlib.md5(email.encode()).hexdigest(),
                email=email,
                created_at=now,
            ))
        await session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    global _bot_service
    await _seed_admin_allowed_emails()
    if settings.TELEGRAM_BOT_TOKEN:
        from app.database import async_session as _session_factory
        _bot_service = TelegramBotService(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            session_factory=_session_factory,
            verification=_verification,
        )
        _bot_service.start()
    yield
    if _bot_service is not None:
        await _bot_service.stop()


app = FastAPI(title="Turbolog", version="0.1.0", lifespan=lifespan)

# CORS middleware for development (disabled in production via same-origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes registered BEFORE static mount
app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(jira_router)
app.include_router(status_router)
app.include_router(telegram_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# --- Static file serving (production only) ------------------------------------
# When SERVE_STATIC is true (set in production), mount the SvelteKit build
# output and add a catch-all route for SPA client-side routing.

SERVE_STATIC = os.getenv("SERVE_STATIC", "false").lower() == "true"
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(Path(__file__).resolve().parent.parent.parent / "frontend" / "build")))


if SERVE_STATIC and STATIC_DIR.is_dir():
    # Mount assets subdirectory (JS, CSS, images with hashed names)
    _assets_dir = STATIC_DIR / "_app" / "immutable"
    if _assets_dir.is_dir():
        app.mount(
            "/_app/immutable",
            StaticFiles(directory=str(_assets_dir)),
            name="spa-assets",
        )

    # Catch-all: serve index.html for any non-API, non-asset route (SPA routing)
    @app.get("/{path:path}")
    async def spa_catchall(request: Request, path: str):
        # Try to serve a real file first (e.g. favicon, manifest)
        file_path = STATIC_DIR / path
        if path and file_path.is_file():
            return FileResponse(str(file_path))
        # Otherwise serve index.html for client-side routing
        index = STATIC_DIR / "index.html"
        # index.html is the SPA entry and references content-hashed JS/CSS. It MUST
        # NOT be cached: otherwise the browser serves a stale bundle (referencing
        # old assets) after a deploy, so new UI (e.g. admin nav links) is missing
        # until a manual refresh. Hashed assets under /_app/immutable stay cacheable.
        no_cache = {"Cache-Control": "no-store"}
        if index.is_file():
            return FileResponse(str(index), headers=no_cache)
        return FileResponse(str(index), headers=no_cache)
