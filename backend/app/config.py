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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
