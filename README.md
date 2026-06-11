# Turbolog

Daily status report tool for JIRA tasks. Connect your JIRA Cloud account, browse assigned tasks, and write daily status updates.

## Architecture

- **Backend**: FastAPI + async SQLAlchemy 2.0 + SQLite (dev) / PostgreSQL (prod)
- **Frontend**: SvelteKit SPA (Svelte 5, adapter-static, ssr: false)
- **Auth**: Google OAuth 2.0 with JWT cookie sessions
- **Design**: Neon/cyberpunk theme (michia.ai style)

## Prerequisites

- Python >= 3.12
- Node.js >= 18
- uv (Python package manager)

## Getting Started

### Backend

```bash
cd backend
uv sync
cp .env.example .env  # Fill in your values
uvicorn app.main:app --reload --port 8000
```

### Frontend (Development)

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

The Vite dev server proxies `/api/*` requests to the FastAPI backend at `http://localhost:8000`.

### Frontend (Production Build)

```bash
cd frontend
npm run build
```

FastAPI serves the built SPA from `frontend/build/` via StaticFiles mount.

## Environment Variables

See `backend/.env.example` for all configuration options.

## License

Private project.
