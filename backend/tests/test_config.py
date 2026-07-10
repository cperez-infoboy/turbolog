"""Tests for app.config: Settings sources + assert_prod_secrets fail-fast.

Covers:
- secrets_dir: genuine secrets read from files under /run/secrets (Docker Swarm).
- case_sensitive=False: mixed-case env var still overrides a field.
- CORS_ORIGINS: default value and env override.
- assert_prod_secrets: PURE function that raises when any must-have secret is
  still its insecure default (DATABASE_URL default, JWT_SECRET dev default,
  empty GOOGLE_CLIENT_SECRET, empty JIRA_API_TOKEN). Empty LLM_API_KEY is a
  documented valid state (feature disabled) and MUST NOT raise.
"""
import pytest

from app.config import Settings, assert_prod_secrets


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fresh(**overrides) -> Settings:
    """Build a Settings instance with NO env file / secrets dir, then override.

    `_env_file=None` disables reading the repo's .env so the test controls every
    value explicitly (deterministic, no pollution from the dev environment).
    """
    return Settings(_env_file=None, _secrets_dir=None, **overrides)


def _secure(**overrides) -> Settings:
    """Settings where every must-have secret is non-default (passes the check)."""
    base = dict(
        DATABASE_URL="postgresql+asyncpg://u:p@host/db",
        JWT_SECRET="a-real-secret",
        GOOGLE_CLIENT_SECRET="GOCSPX-real",
        JIRA_API_TOKEN="real-token",
        LLM_API_KEY="",  # empty is OK (feature off)
    )
    base.update(overrides)
    return _fresh(**base)


# --------------------------------------------------------------------------- #
# secrets_dir
# --------------------------------------------------------------------------- #


class TestSecretsDir:
    def test_reads_field_from_secret_file(self, tmp_path):
        # Field JWT_SECRET is matched by a lowercase field-named file
        # (case_sensitive=False -> file name lookup is case-insensitive).
        (tmp_path / "jwt_secret").write_text("from-secret-file", encoding="utf-8")

        s = Settings(_env_file=None, _secrets_dir=str(tmp_path))

        assert s.JWT_SECRET == "from-secret-file"

    def test_secret_file_overrides_default(self, tmp_path):
        # google_client_secret default is "" -> a mounted secret populates it.
        (tmp_path / "google_client_secret").write_text("GOCSPX-mounted", encoding="utf-8")

        s = Settings(_env_file=None, _secrets_dir=str(tmp_path))

        assert s.GOOGLE_CLIENT_SECRET == "GOCSPX-mounted"


# --------------------------------------------------------------------------- #
# case_sensitive=False
# --------------------------------------------------------------------------- #


class TestCaseSensitive:
    def test_lowercase_env_var_sets_uppercase_field(self, monkeypatch):
        # case_sensitive=False: env var `cors_origins` matches field CORS_ORIGINS.
        monkeypatch.setenv("cors_origins", "https://example.com")

        s = _fresh()

        assert s.CORS_ORIGINS == "https://example.com"


# --------------------------------------------------------------------------- #
# CORS_ORIGINS
# --------------------------------------------------------------------------- #


class TestCorsOrigins:
    def test_default(self):
        s = _fresh()
        assert s.CORS_ORIGINS == "http://localhost:5173"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://a.test,https://b.test")

        s = _fresh()

        assert s.CORS_ORIGINS == "https://a.test,https://b.test"


# --------------------------------------------------------------------------- #
# assert_prod_secrets
# --------------------------------------------------------------------------- #


class TestAssertProdSecrets:
    def test_raises_on_default_database_url(self):
        default_db = Settings.model_fields["DATABASE_URL"].default
        with pytest.raises(RuntimeError):
            assert_prod_secrets(_secure(DATABASE_URL=default_db))

    def test_raises_on_dev_jwt_secret(self):
        with pytest.raises(RuntimeError):
            assert_prod_secrets(_secure(JWT_SECRET="dev-secret-change-me"))

    def test_raises_on_empty_google_client_secret(self):
        with pytest.raises(RuntimeError):
            assert_prod_secrets(_secure(GOOGLE_CLIENT_SECRET=""))

    def test_raises_on_empty_jira_api_token(self):
        with pytest.raises(RuntimeError):
            assert_prod_secrets(_secure(JIRA_API_TOKEN=""))

    def test_passes_when_all_must_haves_are_set(self):
        # No raise.
        assert_prod_secrets(_secure())

    def test_empty_llm_api_key_does_not_raise(self):
        # Documented valid state: empty LLM_API_KEY disables the feature.
        assert_prod_secrets(_secure(LLM_API_KEY=""))

    def test_error_message_mentions_insecure_values(self):
        # Help operators find WHICH secret is missing.
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            assert_prod_secrets(_secure(JWT_SECRET="dev-secret-change-me"))
