# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Resumen del proyecto

Turbolog — herramienta de reportes de estado diario para tareas de JIRA Cloud. Los usuarios se autentican con Google OAuth, ven sus tareas asignadas de JIRA, y escriben actualizaciones de estado diarias por tarea.

## Comandos

### Backend (desde `backend/`)
```bash
uv sync                    # instalar dependencias
uv run alembic upgrade head # ejecutar migraciones de BD
uvicorn app.main:app --reload --port 8000  # servidor de desarrollo
uv run pytest              # ejecutar tests
```

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

El Dockerfile es multi-stage: Node compila el frontend, luego Python arma el backend con los archivos estáticos embebidos. Un solo contenedor, sin volúmenes compartidos.

## Arquitectura

**Monorepo, SPA same-origin**: FastAPI sirve el build estático de SvelteKit, eliminando CORS en producción.

### Backend (`backend/`)
- **FastAPI** + **SQLAlchemy 2.0 async** + **SQLite** (dev) / PostgreSQL (prod)
- **Flujo de auth**: Google OAuth → JWT en cookie `auth_token` → dependency `get_current_user` valida en cada request
- **Integración JIRA**: Token admin global (Basic Auth) vía `jira_client.py`. Tareas cacheadas en BD con TTL (default 300s). Usa JIRA Cloud REST API v3 `/rest/api/3/search/jql` (el endpoint viejo `/search` devuelve 410 Gone)
- **Config**: `pydantic_settings` lee desde `.env` (`backend/app/config.py`)
- **Archivos clave**:
  - `app/main.py` — setup de la app, CORS (solo dev), montaje de archivos estáticos, catch-all para SPA routing
  - `app/dependencies.py` — `get_db_session()`, `get_current_user()` (validación de JWT cookie)
  - `app/routers/auth.py` — flujo Google OAuth, login/register/logout
  - `app/routers/jira.py` — endpoint de listado de tareas
  - `app/routers/status.py` — CRUD para reportes de estado diarios
  - `app/services/jira_client.py` — wrapper de JIRA API (búsqueda por JQL, lookup de usuario)
  - `app/models/` — modelos SQLAlchemy: `User`, `Task`, `StatusReport`

### Frontend (`frontend/`)
- **SvelteKit SPA** (Svelte 5, adapter-static, `ssr: false`, `fallback: 'index.html'`)
- **Cliente API**: `src/lib/api/client.ts` — wrapper de `fetch` con `credentials: 'include'` y headers JSON. Todos los módulos API (`auth.ts`, `tasks.ts`, `status.ts`) usan el helper `api<T>()`.
- **State management**: Runes de Svelte 5 (`$state`) en stores a nivel módulo en `src/lib/stores/`. Los componentes importan getters reactivos vía `getTasksState()`, `getAuthState()`.
- **Proxy Vite**: El dev server proxya `/api/*` a `http://localhost:8081` (ver `vite.config.ts`)
- **Rutas**: `/` (dashboard principal), `/login`, `/register`, `/settings`
- **Patrón UI**: Layout acordeón de una sola columna. Los `TaskCard` se expanden inline para mostrar el editor de status. No hay panel editor separado.
- **Diseño**: Theme neon/cyberpunk oscuro. CSS custom properties en `app.css` (`--neon-cyan`, `--neon-pink`, `--glass-bg`, etc.). Fuentes: Orbitron (títulos), Rajdhani (body). Sin Tailwind.

### Flujo de datos
1. Usuario autentica vía Google OAuth → se setea cookie JWT
2. `+layout.svelte` verifica auth al montar, redirige a `/login` si no autenticado
3. `+page.svelte` obtiene tareas y reportes al montar
4. Las tareas se renderizan como items acordeón `TaskCard` con editores de status inline
5. Los reportes se guardan vía llamadas API `createReport` / `updateReport`
6. Las tareas de JIRA se cachean en la BD del backend con TTL configurable

## Patrones clave

- **Svelte 5**: Usar `$props()`, `$state()`, `$effect()`, `onclick={...}` (no `on:click`). `{#each items as item (item.id)}` con key.
- **Dependencies del backend**: Inyectar `get_current_user` para endpoints protegidos, `get_db_session` para acceso a BD.
- **JIRA JQL**: Usar `accountId` (no email) para el campo `assignee`. Buscar primero vía `/rest/api/3/user/search`.
- **Migraciones**: Alembic auto-genera desde los modelos. Ejecutar `alembic upgrade head` al iniciar.

## Variables de entorno

Ver `backend/.env.example`. Las críticas:
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — OAuth
- `JWT_SECRET` — cambiar en producción
- `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_DOMAIN` — integración JIRA Cloud
- `SERVE_STATIC=true` / `STATIC_DIR=/app/static` — para producción en Docker
