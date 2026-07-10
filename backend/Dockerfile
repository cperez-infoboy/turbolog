# ── Stage 1: Build frontend ──────────────────────────────
FROM node:22-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 2: Backend ─────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Python dependencies
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# Backend source
COPY backend/ .

# Entrypoint: owns the RUN_MIGRATIONS gate (default runs alembic for local dev;
# Swarm sets RUN_MIGRATIONS=false so a one-shot migrate service owns migrations).
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Frontend static files (from Stage 1)
COPY --from=frontend-build /app/build ./static

# Entrypoint runs migrations (unless RUN_MIGRATIONS=false) then execs the CMD.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
