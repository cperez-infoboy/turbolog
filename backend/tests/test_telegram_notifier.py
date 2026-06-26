"""Tests for TelegramNotifier (RED phase).

TelegramNotifier sends a formatted message to a user's Telegram chat
via the Bot API. Uses httpx.AsyncClient to POST to sendMessage.
"""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services.notifier import TelegramNotifier


class _FakeSummary:
    def __init__(self, reported_days, faltas):
        self.reported_days = reported_days
        self.faltas = faltas


class _FakeUser:
    def __init__(self, email, name="Someone", telegram_chat_id=None):
        self.email = email
        self.name = name
        self.telegram_chat_id = telegram_chat_id


class TestTelegramNotifierRemind:
    async def test_sends_message_to_linked_user(self):
        notifier = TelegramNotifier(bot_token="fake-token")
        user = _FakeUser(
            email="dev@example.com",
            name="Dev",
            telegram_chat_id="12345",
        )
        summary = _FakeSummary(reported_days=10, faltas=2)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(status_code=200)
            await notifier.remind(user, date(2026, 6, 24), summary)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "sendMessage" in call_args[0][0]
        assert call_args[1]["json"]["chat_id"] == "12345"
        text = call_args[1]["json"]["text"]
        assert "2026-06-24" in text
        assert "10" in text
        assert "2" in text

    async def test_skips_user_without_chat_id(self):
        notifier = TelegramNotifier(bot_token="fake-token")
        user = _FakeUser(email="dev@example.com", telegram_chat_id=None)
        summary = _FakeSummary(reported_days=5, faltas=1)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            await notifier.remind(user, date(2026, 6, 24), summary)

        mock_post.assert_not_called()

    async def test_handles_api_error_gracefully(self):
        notifier = TelegramNotifier(bot_token="fake-token")
        user = _FakeUser(
            email="dev@example.com",
            telegram_chat_id="999",
        )
        summary = _FakeSummary(reported_days=3, faltas=0)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(
                status_code=403,
                text="Forbidden",
            )
            # Should NOT raise — logs the error and continues.
            await notifier.remind(user, date(2026, 6, 24), summary)

    async def test_message_contains_user_name(self):
        notifier = TelegramNotifier(bot_token="fake-token")
        user = _FakeUser(
            email="a@b.com",
            name="Claudio",
            telegram_chat_id="111",
        )
        summary = _FakeSummary(reported_days=8, faltas=0)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(status_code=200)
            await notifier.remind(user, date(2026, 6, 25), summary)

        text = mock_post.call_args[1]["json"]["text"]
        assert "Claudio" in text
