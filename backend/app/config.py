from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # JWT
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_EXPIRE_HOURS: int = 24

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/turbolog"

    # App
    APP_URL: str = "http://localhost:5173"

    # JIRA (global admin token)
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_DOMAIN: str = ""
    JIRA_CACHE_TTL: int = 300  # seconds
    JIRA_REQUEST_TIMEOUT: int = 10  # seconds

    # LLM (OpenAI-compatible) — status improvement feature.
    # Empty LLM_API_KEY disables the feature (the /improve endpoint returns 503).
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: int = 30  # seconds
    # Completion budget. Counts BOTH reasoning and answer tokens, so reasoning
    # models (e.g. DeepSeek) need headroom or they spend it all on reasoning and
    # return empty content. 4096 is safe for a short daily status.
    LLM_MAX_TOKENS: int = 4096
    # DeepSeek v4 reasoning toggle: "disabled" (fast, no chain-of-thought) or
    # "enabled". Empty = omit the field entirely (for OpenAI and other providers
    # that don't support it). DeepSeek v4 defaults to thinking ENABLED.
    LLM_THINKING: str = ""

    # Audit / reminders
    REMINDER_TIME: str = "17:30"  # "HH:MM" 24h, dias habiles
    AUDIT_TIMEZONE: str = "America/Argentina/Buenos_Aires"  # tz del cron y de "today"
    ADMIN_EMAILS: str = ""  # seed de super-admins (bootstrap, inmutable via API)
    NOTIFIER_MODE: str = "log"  # "log" | "telegram"
    ENABLE_SCHEDULER: bool = True  # true en contenedor scheduler; false en web

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""  # vacío deshabilita el bot
    TELEGRAM_BOT_USERNAME: str = "TurbologBot"  # para deep link en frontend
    TELEGRAM_CODE_TTL_SECONDS: int = 300  # 5 min para verificar código

    # CORS — comma-separated origins. Same-origin in prod (Cloudflare serves
    # frontend + API); split into a sequence at the call site in main.py.
    CORS_ORIGINS: str = "http://localhost:5173"

    # secrets_dir reads genuine Docker Swarm secrets from /run/secrets (field-
    # named files). case_sensitive=False lets a lowercase secret/env name match
    # an UPPERCASE field (Swarm secret targets use the field name). A missing
    # /run/secrets dir in dev is silently ignored by pydantic-settings.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "secrets_dir": "/run/secrets",
        "case_sensitive": False,
    }


def assert_prod_secrets(settings: Settings) -> None:
    """Fail fast if a must-have secret is still its insecure default.

    PURE (no FastAPI coupling). Called from BOTH the FastAPI lifespan and the
    scheduler entrypoint (the scheduler runs under asyncio.run with no lifespan,
    so without this it would skip the check). pydantic ``secrets_dir`` silently
    falls back to defaults when a secret file is missing, so this catches an
    unmounted prod secret.

    Must-have list (raises on insecure default):
    - ``DATABASE_URL`` == the built-in default (unconfigured).
    - ``JWT_SECRET`` == ``"dev-secret-change-me"``.
    - ``GOOGLE_CLIENT_SECRET`` == ``""`` (empty default => broken auth).
    - ``JIRA_API_TOKEN`` == ``""`` (empty default => broken JIRA).

    ``LLM_API_KEY == ""`` is NOT a failure: it is a documented valid state that
    disables the status-improvement feature.
    """
    default_database_url = Settings.model_fields["DATABASE_URL"].default
    issues: list[str] = []
    if settings.DATABASE_URL == default_database_url:
        issues.append("DATABASE_URL is still the built-in default")
    if settings.JWT_SECRET == "dev-secret-change-me":
        issues.append("JWT_SECRET is the dev default 'dev-secret-change-me'")
    if settings.GOOGLE_CLIENT_SECRET == "":
        issues.append("GOOGLE_CLIENT_SECRET is empty")
    if settings.JIRA_API_TOKEN == "":
        issues.append("JIRA_API_TOKEN is empty")
    if issues:
        raise RuntimeError("Insecure production secrets: " + "; ".join(issues))


def prod_secrets_dir_exists() -> bool:
    """True only when /run/secrets exists (Docker Swarm prod).

    Used to gate ``assert_prod_secrets`` so dev (no such dir) never trips it
    even when insecure defaults are present. Kept here next to
    ``assert_prod_secrets`` as a cohesive fail-fast pair; imported by both the
    FastAPI lifespan (main.py) and the scheduler entrypoint
    (scheduler_runner.py) so neither duplicates the check nor imports the other.
    """
    return Path("/run/secrets").exists()


settings = Settings()
