"""Telegram bot service: long-polling background task.

Runs inside the FastAPI process. Polls Telegram for updates and handles:
- ``/start`` → reply with instructions to link via Turbolog
- 6-digit code → verify against the :class:`VerificationStore` and save
  the ``telegram_chat_id`` on the matching User row.

Start/stop via :meth:`TelegramBotService.start` / :meth:`stop`.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from sqlalchemy import select

from app.models.user import User
from app.services.telegram_verification import VerificationStore

logger = logging.getLogger("turbolog.telegram_bot")

_CODE_RE = re.compile(r"^\d{6}$")


class TelegramBotService:
    """Background Telegram bot using long polling."""

    def __init__(
        self,
        bot_token: str,
        session_factory,
        verification: VerificationStore,
    ) -> None:
        self._token = bot_token
        self._api = f"https://api.telegram.org/bot{bot_token}"
        self._session_factory = session_factory
        self._verification = verification
        self._task: asyncio.Task | None = None
        self._running = False

    # -- Public API -----------------------------------------------------------

    def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram bot started")

    async def stop(self) -> None:
        """Signal the polling loop to stop and wait for it."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Telegram bot stopped")

    # -- Polling loop ---------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Long-poll Telegram for updates until ``_running`` is False."""
        offset = 0
        while self._running:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self._api}/getUpdates",
                        params={"offset": offset, "timeout": 30},
                        timeout=35,
                    )
                if resp.status_code != 200:
                    logger.warning("getUpdates %s: %s", resp.status_code, resp.text)
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Telegram poll error")
                await asyncio.sleep(5)

    # -- Update handling ------------------------------------------------------

    async def _handle_update(self, update: dict) -> None:
        """Route a single Telegram update to the appropriate handler."""
        message = update.get("message")
        if not message:
            return

        text: str = (message.get("text") or "").strip()
        chat_id = str(message["chat"]["id"])

        if text == "/start":
            await self._handle_start(chat_id)
        elif _CODE_RE.match(text):
            await self._handle_code(text, chat_id)
        else:
            await self._send_message(
                chat_id,
                "Envía /start para ver las instrucciones, o un código de 6 dígitos para vincular tu cuenta.",
            )

    async def _handle_start(self, chat_id: str) -> None:
        """Reply with linking instructions."""
        await self._send_message(
            chat_id,
            "👋 ¡Hola! Soy el bot de Turbolog.\n\n"
            "Para vincular tu cuenta, genera un código desde la aplicación "
            "y envíamelo aquí.",
        )

    async def _handle_code(self, code: str, chat_id: str) -> None:
        """Process a 6-digit verification code."""
        success = await self._process_code(code, chat_id)
        if success:
            await self._send_message(
                chat_id,
                "✅ ¡Cuenta vinculada! Ahora recibirás recordatorios por Telegram.",
            )
        else:
            await self._send_message(
                chat_id,
                "❌ Código inválido o expirado. Genera uno nuevo desde Turbolog.",
            )

    async def _process_code(self, code: str, chat_id: str) -> bool:
        """Verify a code and save the chat_id on the user. Returns True on success."""
        user_id = self._verification.consume_code(code)
        if user_id is None:
            return False

        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                logger.warning("Code %s matched user_id %s but user not found", code, user_id)
                return False

            user.telegram_chat_id = chat_id
            await session.commit()

        logger.info("Telegram linked: user %s -> chat %s", user_id, chat_id)
        return True

    # -- Helpers --------------------------------------------------------------

    async def _send_message(self, chat_id: str, text: str) -> None:
        """Send a text message via the Telegram Bot API."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._api}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "sendMessage to %s failed: %s %s",
                        chat_id,
                        resp.status_code,
                        resp.text,
                    )
        except Exception:
            logger.exception("sendMessage error for %s", chat_id)
