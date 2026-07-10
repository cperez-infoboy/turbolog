"""Tests for the scheduler entrypoint prod-secrets fail-fast.

The scheduler runs under ``asyncio.run`` with NO FastAPI lifespan, so without an
explicit check it would skip ``assert_prod_secrets`` entirely. The sync ``run()``
entrypoint asserts (gated on /run/secrets, same as the web lifespan) BEFORE
``asyncio.run`` starts the loop — so an unmounted prod secret aborts the
scheduler before it can do work.
"""
import pytest

from app.config import settings


def _secure(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setattr(settings, "JWT_SECRET", "a-real-secret")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "GOCSPX-real")
    monkeypatch.setattr(settings, "JIRA_API_TOKEN", "real-token")


class TestSchedulerProdGate:
    def test_run_raises_before_loop_on_insecure_secret(self, monkeypatch):
        from app.scheduler_runner import run

        # Prod env (secrets dir exists) + insecure JWT => must raise.
        monkeypatch.setattr("app.scheduler_runner.prod_secrets_dir_exists", lambda: True)
        monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-change-me")

        # asyncio.run must NEVER be reached: a spy proves it.
        loop_started = {"yes": False}

        def _spy_asyncio_run(_coro):
            loop_started["yes"] = True

        monkeypatch.setattr("app.scheduler_runner.asyncio.run", _spy_asyncio_run)

        with pytest.raises(RuntimeError):
            run()

        assert loop_started["yes"] is False, "asyncio.run must not be reached on insecure secrets"

    def test_run_dev_skips_assert_and_starts_loop(self, monkeypatch):
        from app.scheduler_runner import run

        # Dev: no /run/secrets => assert skipped, even with insecure defaults.
        monkeypatch.setattr("app.scheduler_runner.prod_secrets_dir_exists", lambda: False)
        monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-change-me")
        # Force ENABLE_SCHEDULER False so main() returns immediately (no real loop).
        monkeypatch.setattr(settings, "ENABLE_SCHEDULER", False)

        loop_started = {"yes": False}

        def _spy_asyncio_run(coro):
            loop_started["yes"] = True
            # Drive the coroutine once so it returns without sleeping.
            import asyncio as _asyncio

            _asyncio.get_event_loop().run_until_complete(coro)

        # Replace the real asyncio.run with the real one (we just need to prove
        # it IS reached in dev). main() returns immediately due to the flag.
        monkeypatch.setattr(
            "app.scheduler_runner.asyncio.run",
            lambda coro: loop_started.__setitem__("yes", True),
        )

        run()  # must NOT raise

        assert loop_started["yes"] is True, "asyncio.run MUST be reached in dev"

    def test_run_prod_secure_starts_loop(self, monkeypatch):
        from app.scheduler_runner import run

        monkeypatch.setattr("app.scheduler_runner.prod_secrets_dir_exists", lambda: True)
        _secure(monkeypatch)
        monkeypatch.setattr(settings, "ENABLE_SCHEDULER", False)

        loop_started = {"yes": False}
        monkeypatch.setattr(
            "app.scheduler_runner.asyncio.run",
            lambda coro: loop_started.__setitem__("yes", True),
        )

        run()  # must NOT raise

        assert loop_started["yes"] is True
