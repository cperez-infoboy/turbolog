# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Idioma del proyecto

Los textos de la UI están en **español neutro** (nunca voseo). Usa siempre "tú" conjugaciones. Ejemplos: "No tienes tareas", "Revisa tu status", "Configura notificaciones". Esto aplica a labels, mensajes de error, placeholders, tooltips, y cualquier string visible al usuario.

## Resumen del proyecto

Turbolog — herramienta de reportes de estado diario para tareas de JIRA Cloud. Los usuarios se autentican con Google OAuth, ven sus tareas asignadas de JIRA, escriben actualizaciones de estado diarias por tarea, y las publican en JIRA al "Cerrar día". Incluye **auditoría mensual de cumplimiento**, **recordatorios automáticos a las 17:30**, **notificaciones por Telegram**, **control de acceso por allow-list de correos**, y un **panel de administración**.

## Comandos

### Backend (desde `backend/`)
```bash
uv sync                     # instalar dependencias
uv run alembic upgrade head # ejecutar migraciones de BD
uv run pytest -q            # suite de tests (strict TDD)
uvicorn app.main:app --reload --port 8081  # dev sin Docker (debe ser 8081, ver nota)
```

> **Puerto 8081, no 8000**: el proxy de Vite apunta a `localhost:8081` ([`frontend/vite.config.ts`](frontend/vite.config.ts)). En dev sin Docker el backend **debe** escuchar en `8081`. El `8000` es el puerto *interno* del contenedor Docker, mapeado a host `8081`.

**Tests**: `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`). Harness en [`tests/conftest.py`](backend/tests/conftest.py): in-memory SQLite por test (`Base.metadata.create_all`); los routers abren su propia `async_session()` directo → los tests **parchean** `<router>.async_session = session_factory` y sobreescriben `get_current_user`/`get_jira_client` vía `app.dependency_overrides`. Strict TDD está activo.

### Frontend (desde `frontend/`)
```bash
npm install                # instalar dependencias
npm run dev -- --port 5173 # servidor dev (proxy /api → localhost:8081)
npm run build              # build producción → frontend/build/
npm run check              # svelte-check (errores de tipos)
```

### Docker (desde la raíz del repo)
```bash
docker compose up -d --build    # build + iniciar (backend + scheduler)
docker compose down -v          # detener + eliminar volúmenes
```

Dos servicios, **misma imagen** (multi-stage: Node compila el frontend, Python arma el backend con estáticos embebidos):
- **backend** — FastAPI + SPA estática. Internamente `8000`, host `8081`. Healthcheck `GET /api/health`.
- **scheduler** — procesos programados. `command: uv run python -m app.scheduler_runner`. Sin puertos. Depende de `backend` (healthy).

## Arquitectura

**Monorepo, SPA same-origin**: FastAPI sirve el build estático de SvelteKit, eliminando CORS en producción.

### Backend (`backend/`)
- **FastAPI** + **SQLAlchemy 2.0 async** + **PostgreSQL** (externo, vía `DATABASE_URL`). JWT con `python-jose`, HTTP a JIRA con `httpx`, LLM OpenAI-compatible con `openai`. Package manager: `uv`.
- **Auth + control de acceso**: Google OAuth → JWT en cookie `auth_token` → `get_current_user` valida en cada request. **Allow-list de correos** (`allowed_emails`): `can_login(email)` se revisa en **cada login** (`google_callback`); quitar un correo revoca el acceso en el próximo intento. Seed `ADMIN_EMAILS` siempre permitido (bootstrap al login verificado por Google).
- **Roles**: `User.is_admin` (DB) + seed `ADMIN_EMAILS` (inmutable vía API). `require_admin` = flag OR seed. `User.is_audited` = sujeto a reporte de status.
- **JIRA**: token admin global (Basic Auth) vía `jira_client.py`. Tareas cacheadas en BD con TTL (default 300s). JIRA Cloud REST API v3 `POST /rest/api/3/search/jql`. JQL: `assignee=<accountId> AND statusCategory != Done ORDER BY updated DESC`.
- **Config**: `pydantic_settings` lee `.env` (`backend/app/config.py`). Las flags `SERVE_STATIC` / `STATIC_DIR` son excepción: se leen con `os.getenv`.
- **Archivos clave**:
  - `app/main.py` — setup de la app, CORS (solo dev), montaje de estáticos, catch-all SPA (`index.html` con `Cache-Control: no-store`), `/api/health`
  - `app/dependencies.py` — `get_current_user`, `require_admin`, `is_super_admin`, `can_login`, `_admin_seed`, `get_notifier`
  - `app/routers/auth.py` — Google OAuth, login/register/logout, `/me` (+`is_admin`), gate `can_login` en callback/register
  - `app/routers/jira.py` — listado de tareas + cache DB-backed (`/api/jira`)
  - `app/routers/status.py` — CRUD de status, `/improve` (LLM), `/finalize` (Cerrar día), `/summary` (contador mensual propio)
  - `app/routers/audit.py` — admin: `GET /users`, `PATCH /users/{id}` (anti-lockout + seed inmutable, expone `is_seed`), `GET /monthly` (solo auditados), `POST /run-reminders`, `GET/POST/DELETE /allowed-emails`
  - `app/routers/telegram.py` — `GET /status` (linked/chat_id), `POST /link` (genera código de verificación), `DELETE /link` (desvincula)
  - `app/services/` — `jira_client.py`, `llm_client.py`, `audit_service.py` (cómputo puro de faltas, toma `session_factory`), `notifier.py` (`Notifier` Protocol / `LogNotifier` / `TelegramNotifier` / `build_notifier`), `telegram_bot.py` (long polling, verificación de código), `telegram_verification.py` (store in-memory con TTL)
  - `app/jobs/` — `reminder.py` (core puro + job, solo auditados), `registry.py` (`JobSpec` + `build_jobs`, **punto de extensión** para más procesos), `engine.py` (APScheduler start/stop)
  - `app/scheduler_runner.py` — entrypoint del contenedor scheduler (`AsyncIOScheduler`, graceful SIGTERM)
  - `app/models/` — `User` (+`is_admin`/`is_audited`/`telegram_chat_id`), `Task` (+`status_category`), `StatusReport` (+`jira_comment_id`), `DailyClosure`, `AllowedEmail`, `AuditPeriod`

#### Auditoría, recordatorios y control de acceso
- **"Día cumplido"** = existe `DailyClosure(user, date)` (señal autoritativa; contar `StatusReport` sueltos escondería faltas). **"Falta"** = día hábil Lun-Vie sin cierre (sin feriados/excepciones en v1; los días hábiles futuros del mes no se cuentan).
- `audit_service`: `expected_weekdays` (Lun-Vie ≤ hoy), `compute_month_audit/summary/for_all_users`. **Derivado on-the-fly** de `daily_closures` (no se persisten snapshots).
- **Recordatorio 17:30** (días hábiles): `process_user_for_reminder` → si hoy no cumplió, `notifier.remind`. Motor `AsyncIOScheduler` (jobs como coroutines, comparten `async_session`); `coalesce`, `misfire_grace_time=3600`, `max_instances=1`.
- **Contenedor scheduler dedicado**: misma imagen que el backend, solo cambia el `command`. El web no tiene reloj. Añadir procesos futuros = un `JobSpec` en `jobs/registry.build_jobs`.
- **Allow-list**: tabla `allowed_emails`; `can_login` en cada login (revocación real). La migración siembra la lista con los `DISTINCT lower(email)` de los usuarios existentes (nadie queda bloqueado al desplegar).

#### Notificaciones Telegram
- **Telegram Bot** corre como background task dentro de FastAPI (long polling con `httpx`). Arranca en el lifespan si `TELEGRAM_BOT_TOKEN` está configurado.
- **Verificación con código**: usuario hace click "Vincular Telegram" en el frontend → backend genera código de 6 dígitos (TTL 5 min, store in-memory) → usuario envía código al bot → bot guarda `telegram_chat_id` en el User.
- `TelegramNotifier` implementa `Notifier` Protocol. `build_notifier(settings)` con `NOTIFIER_MODE="telegram"` lo instancia.
- El bot solo envía a usuarios con `telegram_chat_id` seteado. Sin chat_id → skip silencioso.
- **Frontend**: panel "Notificaciones Telegram" en el dashboard (`/`) con estado de vinculación, código, y link deep-link al bot.

#### Modelo `Task` — campo `status_category`
`status_category` (String, nullable) desde `fields.status.statusCategory.key` de JIRA — valores `new` / `indeterminate` / `done`. Migración: `aa0c300eac79`.

### Frontend (`frontend/`)
- **SvelteKit SPA** (Svelte 5, adapter-static, `ssr: false`, `prerender: false`, `fallback: 'index.html'`). **No hay `svelte.config.js`**: toda la config (adapter-static, fallback, runes forzadas, proxy Vite) vive en [`vite.config.ts`](frontend/vite.config.ts). `ssr`/`prerender` se setean en `+layout.ts`.
- **Rutas**: `/` (dashboard), `/login`, `/register`, `/administracion` (admin: usuarios + allow-list + recordatorios), `/auditoria` (admin: reporte mensual), `/no-access` (pública, sin acceso).
- **Cliente API**: `src/lib/api/client.ts` — `fetch` con `credentials: 'include'`, **`cache: 'no-store'`** (evita responses stale), headers JSON. Lanza `ApiError` (con `.status`) en no-ok y **short-circuit en 401**. Módulos `auth.ts`, `tasks.ts`, `status.ts`, `audit.ts` usan `api<T>()`.
- **State management**: Runes de Svelte 5 en `src/lib/stores/*.svelte.ts` (los archivos **deben** llamarse `*.svelte.ts`). Patrón getter-factory: `getTasksState()` / `getAuthState()` (con `isAdmin`). `checkAuth()` se llama al montar en `+layout.svelte`.
- **Patrón UI**: Layout acordeón de una sola columna. `TaskCard` se expande inline para el editor de status (gate por `status_category === 'indeterminate'`). Theme neon/cyberpunk oscuro (tokens en `app.css`: `--neon-cyan/-pink/-green`, `--glass-bg`; Orbitron/Rajdhani). Sin Tailwind. CSS scoped.
- **Panel admin** (`/administracion`, `/auditoria`): admin-only (guard `$effect` + link en Header solo si `is_admin`). Toggles optimistas (Auditado/Admin) con locks para seed/último admin; allow-list con lock para seed/propio correo.

### Flujo de datos
1. Google OAuth → cookie JWT (solo si `can_login(email)` pasa; si no, redirect a `/no-access`).
2. `+layout.svelte` llama `checkAuth()` al montar; si no autenticado (y no es ruta pública) redirige a `/login`.
3. `/` obtiene tareas/reportes; "Cerrar día" (`/finalize`) publica cada status como comentario JIRA y bloquea el día.
4. Admin: `/administracion` gestiona auditados/admins/allow-list; `/auditoria` ve faltas mensuales. El recordatorio 17:30 corre en el contenedor `scheduler` (solo a usuarios `is_audited` sin cierre del día).

## Patrones clave

- **Svelte 5**: `$props()`, `$state()`, `$derived()`, `$effect()`, `onclick={...}` (no `on:click`). `{#each items as item (item.id)}` con key. Stores en `.svelte.ts` vía getter-factory. Validar componentes nuevos con `svelte-autofixer` (MCP Svelte).
- **Dependencies del backend**: `get_current_user` (protegidos), `require_admin` (admin), `get_notifier`. Los routers abren `async_session()` directo (testeable parcheando el módulo).
- **Auditoría**: derivada on-the-fly de `daily_closures`. `audit_service.compute_*` toman el `session_factory` (abren su propia sesión).
- **Caching**: `cache: 'no-store'` en `api<T>()` (responses siempre frescos); `index.html` servido con `Cache-Control: no-store` (evita servir bundle SPA stale tras un deploy). Los assets hasheados (`/_app/immutable`) sí son cacheables.
- **JIRA JQL**: `accountId` (no email) para `assignee`. Filtrar `statusCategory != Done`.
- **Migraciones**: Alembic auto-genera desde los modelos. `alembic upgrade head` al iniciar (CMD del backend). Head actual: `c1d2e3f4a5b6`.

## Variables de entorno

Ver [`backend/.env.example`](backend/.env.example). Definidas en [`backend/app/config.py`](backend/app/config.py):

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — OAuth Google
- `JWT_SECRET` — cambiar en producción (default `dev-secret-change-me`)
- `JWT_EXPIRE_HOURS` — duración del JWT (default `24`)
- `DATABASE_URL` — PostgreSQL externo (ej. `postgresql+asyncpg://user:pass@host:5432/turbolog`)
- `APP_URL` — URL pública para redirects OAuth (default `http://localhost:5173`)
- `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_DOMAIN` — integración JIRA Cloud
- `JIRA_CACHE_TTL` — TTL del cache de tareas en segundos (default `300`); `JIRA_REQUEST_TIMEOUT` (default `10`)
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_THINKING` — mejora de status con LLM (vacío deshabilita)
- `ADMIN_EMAILS` — seed de super-admins (inmutable vía API; bootstrap al login verificado por Google)
- `REMINDER_TIME` (`"17:30"`, HH:MM 24h días hábiles) · `AUDIT_TIMEZONE` (**tzdb key válido**, ej. `America/Santiago`, NO `America/Chile/Santiago`) · `NOTIFIER_MODE` (`"log"`, `"telegram"`) · `ENABLE_SCHEDULER` (bool)
- `TELEGRAM_BOT_TOKEN` — token del bot de Telegram (vacío deshabilita) · `TELEGRAM_BOT_USERNAME` — username del bot para deep links (default `TurbologBot`) · `TELEGRAM_CODE_TTL_SECONDS` — TTL del código de verificación (default `300`)
- `SERVE_STATIC=true` / `STATIC_DIR=/app/static` — producción en Docker (leídas vía `os.getenv`, no pydantic)
