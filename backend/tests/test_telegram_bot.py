"""Tests for the Telegram bot service (RED phase).

The bot processes incoming Telegram messages:
- /start → reply with instructions
- 6-digit code → verify and link chat_id to user
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.telegram_bot import TelegramBotService


class _FakeUser:
    def __init__(self, id="u1", email="a@b.com", telegram_chat_id=None):
        self.id = id
        self.email = email
        self.telegram_chat_id = telegram_chat_id


class TestProcessStartCommand:
    async def test_sends_instructions_on_start(self):
        bot = TelegramBotService.__new__(TelegramBotService)
        bot._token = "fake"
        bot._api = "https://api.telegram.org/botfake"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(status_code=200)
            await bot._send_message("123", "test")

        mock_post.assert_called_once()
        assert mock_post.call_args[1]["json"]["chat_id"] == "123"


class TestProcessCodeMessage:
    async def test_valid_code_links_user(self):
        from app.services.telegram_verification import VerificationStore

        store = VerificationStore(ttl_seconds=300)
        code = store.create_code("user-42")

        bot = TelegramBotService.__new__(TelegramBotService)
        bot._token = "fake"
        bot._api = "https://api.telegram.org/botfake"
        bot._verification = store
        bot._session_factory = None  # patched below

        # Mock the DB operations.
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_user = _FakeUser(id="user-42")
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute = AsyncMock(return_value=mock_result)

        class _FakeSessionFactory:
            def __call__(self):
                return _AsyncCtx(mock_session)

        class _AsyncCtx:
            def __init__(self, s):
                self._s = s
            async def __aenter__(self):
                return self._s
            async def __aexit__(self, *a):
                pass

        bot._session_factory = _FakeSessionFactory()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(status_code=200)
            result = await bot._process_code(code, "chat-999")

        assert result is True
        assert mock_user.telegram_chat_id == "chat-999"
        mock_session.commit.assert_called_once()

    async def test_invalid_code_returns_false(self):
        from app.services.telegram_verification import VerificationStore

        store = VerificationStore(ttl_seconds=300)
        bot = TelegramBotService.__new__(TelegramBotService)
        bot._token = "fake"
        bot._api = "https://api.telegram.org/botfake"
        bot._verification = store

        result = await bot._process_code("000000", "chat-999")
        assert result is False
