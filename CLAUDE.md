# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Resumen del proyecto

Turbolog — herramienta de reportes de estado diario para tareas de JIRA Cloud. Los usuarios se autentican con Google OAuth, ven sus tareas asignadas de JIRA, y escriben actualizaciones de estado diarias por tarea.

## Comandos

### Backend (desde `backend/`)
```bash
uv sync                     # instalar dependencias
uv run alembic upgrade head # ejecutar migraciones de BD
uvicorn app.main:app --reload --port 8081  # dev sin Docker (debe ser 8081, ver nota)
```

> **Puerto 8081, no 8000**: el proxy de Vite apunta a `localhost:8081` ([`frontend/vite.config.ts`](frontend/vite.config.ts)). En dev sin Docker el backend **debe** escuchar en `8081` para que el frontend lo encuentre. El `8000` solo aparece como puerto *interno* del contenedor Docker, mapeado a host `8081`.

Sin suite de tests todavía; `pytest` y `pytest-asyncio` están en dev deps pero no hay archivos de test.

### Frontend (desde `frontend/`)
```bash
npm install                # instalar dependencias
npm run dev -- --port 5173 # servidor dev (proxy /api → localhost:8081)
npm run build              # build producción → frontend/build/
npm run check              # svelte-check (errores de tipos)
```

### Docker (un solo comando, desde la raíz del repo)
```bash
docker compose up -d --build    # build + iniciar (contenedor único)
docker compose down -v          # detener + eliminar volúmenes
```

El Dockerfile es multi-stage: Node compila el frontend, luego Python arma el backend con los archivos estáticos embebidos. Un solo contenedor, sin volúmenes compartidos. Internamente escucha en `8000`, publicado en host `8081` (mapeo `8081:8000`). Healthcheck sobre `GET /api/health`.

## Arquitectura

**Monorepo, SPA same-origin**: FastAPI sirve el build estático de SvelteKit, eliminando CORS en producción.

### Backend (`backend/`)
- **FastAPI** + **SQLAlchemy 2.0 async** + **SQLite** (dev) / PostgreSQL (prod). JWT con `python-jose`, HTTP a JIRA con `httpx`. Package manager: `uv`.
- **Flujo de auth**: Google OAuth → JWT en cookie `auth_token` → dependency `get_current_user` valida en cada request
- **Integración JIRA**: Token admin global (Basic Auth) vía `jira_client.py`. Tareas cacheadas en BD con TTL (default 300s). Usa JIRA Cloud REST API v3 `POST /rest/api/3/search/jql` (el endpoint viejo `GET /search` devuelve 410 Gone). JQL: `assignee=<accountId> AND statusCategory != Done ORDER BY updated DESC`.
- **Config**: `pydantic_settings` lee desde `.env` (`backend/app/config.py`). Las flags `SERVE_STATIC` / `STATIC_DIR` son excepción: se leen directo con `os.getenv` (no vía pydantic).
- **Archivos clave**:
  - `app/main.py` — setup de la app, CORS (solo dev), montaje de archivos estáticos, catch-all para SPA routing, endpoint `/api/health`
  - `app/dependencies.py` — `get_db_session()`, `get_current_user()` (validación de JWT cookie)
  - `app/routers/auth.py` — flujo Google OAuth, login/register/logout (`/api/auth`)
  - `app/routers/jira.py` — endpoint de listado de tareas + lógica de cache DB-backed (`/api/jira`)
  - `app/routers/status.py` — CRUD para reportes de estado diarios (`/api/status`)
  - `app/services/jira_client.py` — wrapper de JIRA API (búsqueda por JQL, lookup de usuario). Excepciones: `JiraAuthError`→500, `JiraRateLimitError`→503, `JiraError`→502
  - `app/models/` — modelos SQLAlchemy: `User`, `Task`, `StatusReport`

#### Cache de tareas (DB-backed, no in-memory)
`jira.py` consulta rows de `Task` donde `fetched_at >= now - JIRA_CACHE_TTL`. En miss, hace **upsert** por `(user_id, jira_key)` y refresca `fetched_at`. El query param `?refresh=true` fuerza fetch a JIRA saltando el cache. En `JiraRateLimitError` (429) o `JiraError`, sirve cache stale (ignorando TTL) y devuelve `{"tasks": [...], "stale": true}`.

#### Modelo `Task` — campo `status_category`
`status_category` (String, nullable) se popula desde `fields.status.statusCategory.key` de JIRA — valores canónicos `new` / `indeterminate` / `done`, que normalizan los estados que varían de nombre por proyecto (ej. "In Progress", "Code Review"). Migración: `aa0c300eac79`.

### Frontend (`frontend/`)
- **SvelteKit SPA** (Svelte 5, adapter-static, `ssr: false`, `prerender: false`, `fallback: 'index.html'`). **No hay `svelte.config.js`**: toda la config (adapter-static, fallback, runes forzadas, proxy Vite) vive en [`vite.config.ts`](frontend/vite.config.ts). `ssr`/`prerender` se setean en `+layout.ts`.
- **Rutas**: `/` (dashboard principal), `/login`, `/register`. (El dir `settings/` está vacío, sin página todavía.)
- **Cliente API**: `src/lib/api/client.ts` — wrapper de `fetch` con `credentials: 'include'` y headers JSON. Lanza `ApiError` (con `.status`) en no-ok y **short-circuit en 401** (el auth store depende de esto para detectar sesión caída). Los módulos `auth.ts`, `tasks.ts`, `status.ts` usan el helper `api<T>()`.
- **`tasks.ts` maneja dos response shapes**: `Task[]` (cache fresca) o `{ tasks, stale: true }` (fallback stale de JIRA).
- **State management**: Runes de Svelte 5 en `src/lib/stores/`. Los archivos **deben** llamarse `*.svelte.ts` (sino las runes no compilan fuera de componentes). Patrón getter-factory: `getTasksState()` / `getAuthState()` devuelven un objeto de getters reactivos; las acciones (`fetchTasks`, `checkAuth`, etc.) se exportan junto al getter.
- **Proxy Vite**: el dev server proxya `/api` a `http://localhost:8081` ([`vite.config.ts`](frontend/vite.config.ts)).
- **Patrón UI**: Layout acordeón de una sola columna. Los `TaskCard` se expanden inline para mostrar el editor de status — no hay panel editor separado. El editor se **gatea** por `task.status_category === 'indeterminate'`; el resto muestra un aviso de "tarea pendiente".
- **Diseño**: Theme neon/cyberpunk oscuro. CSS custom properties en `app.css` (`--neon-cyan`, `--neon-pink`, `--neon-green`, `--glass-bg`, etc.). Fuentes: Orbitron (títulos), Rajdhani (body). Sin Tailwind. CSS scoped por componente.

### Flujo de datos
1. Usuario autentica vía Google OAuth → se setea cookie JWT
2. `+layout.svelte` llama `checkAuth()` al montar; muestra pantalla "Cargando..." y, si no autenticado (y no está en ruta pública), redirige a `/login` vía `window.location.href`
3. `+page.svelte` obtiene tareas y reportes al montar; un selector de fecha recarga los reportes
4. Las tareas se renderizan como items acordeón `TaskCard` con editores de status inline
5. Los reportes se guardan vía llamadas API `createReport` / `updateReport`
6. Las tareas de JIRA se cachean en la BD del backend con TTL configurable

## Patrones clave

- **Svelte 5**: Usar `$props()`, `$state()`, `$effect()`, `onclick={...}` (no `on:click`). `{#each items as item (item.id)}` con key. Stores en archivos `.svelte.ts`, exportados vía getter-factory (`getXxxState()`).
- **Dependencies del backend**: Inyectar `get_current_user` para endpoints protegidos, `get_db_session` para acceso a BD.
- **JIRA JQL**: Usar `accountId` (no email) para el campo `assignee`. Buscar primero vía `/rest/api/3/user/search`. Filtrar `statusCategory != Done`.
- **Cache de JIRA**: DB-backed por `fetched_at`, upsert por `(user_id, jira_key)`. No crear cache in-memory.
- **Migraciones**: Alembic auto-genera desde los modelos. Ejecutar `alembic upgrade head` al iniciar (el contenedor Docker lo hace en el CMD).

## Variables de entorno

Ver [`backend/.env.example`](backend/.env.example). Definidas en [`backend/app/config.py`](backend/app/config.py):

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — OAuth Google
- `JWT_SECRET` — cambiar en producción (default `dev-secret-change-me`)
- `JWT_EXPIRE_HOURS` — duración del JWT (default `24`)
- `DATABASE_URL` — dev default `sqlite+aiosqlite:///./turbolog.db`; prod usa `sqlite+aiosqlite:///./data/turbolog.db` con volumen `backend-data`
- `APP_URL` — URL pública de la app para redirects OAuth (default `http://localhost:5173`)
- `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_DOMAIN` — integración JIRA Cloud
- `JIRA_CACHE_TTL` — TTL del cache de tareas en segundos (default `300`)
- `JIRA_REQUEST_TIMEOUT` — timeout de requests a JIRA en segundos (default `10`)
- `SERVE_STATIC=true` / `STATIC_DIR=/app/static` — para producción en Docker (leídas vía `os.getenv`, no pydantic)
