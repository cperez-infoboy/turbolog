import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers.auth import router as auth_router
from app.routers.audit import router as audit_router
from app.routers.jira import router as jira_router
from app.routers.status import router as status_router

app = FastAPI(title="Turbolog", version="0.1.0")

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
