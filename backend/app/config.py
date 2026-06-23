from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # JWT
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_EXPIRE_HOURS: int = 24

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./turbolog.db"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
