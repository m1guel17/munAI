"""Telegram channel adapter — active polling via aiogram 3.x."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from .base import ChannelAdapter

if TYPE_CHECKING:
    from ..agent.runtime import AgentRuntime
    from ..audit.logger import AuditLogger
    from ..config import TelegramChannelConfig
    from ..gateway.lane_queue import LaneQueue
    from ..gateway.session_router import SessionRouter
    from .pairing import PairingManager

log = logging.getLogger(__name__)

# Telegram's hard limit on message length
_TELEGRAM_MAX_CHARS = 4096


class TelegramAdapter(ChannelAdapter):
    """Active channel adapter that polls Telegram for messages.

    Lifecycle managed by GatewayServer: ``connect()`` starts polling,
    ``disconnect()`` cancels the polling task and closes the bot session.

    The adapter uses aiogram's Router-based handler registration.
    aiogram is an optional dependency — an ImportError is raised at instantiation
    if it is not installed.
    """

    def __init__(
        self,
        config: TelegramChannelConfig,
        pairing: PairingManager,
        lane_queue: LaneQueue,
        session_router: SessionRouter,
        runtime: AgentRuntime,
        audit: AuditLogger,
    ) -> None:
        try:
            import aiogram  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Telegram support requires aiogram. "
                "Install with: pip install 'munai[telegram]'"
            ) from exc

        self._config = config
        self._pairing = pairing
        self._lane_queue = lane_queue
        self._session_router = session_router
        self._runtime = runtime
        self._audit = audit

        self._bot: Any = None
        self._dp: Any = None
        self._poll_task: asyncio.Task | None = None

    def is_running(self) -> bool:
        """Return True if the polling task is alive."""
        return self._poll_task is not None and not self._poll_task.done()

    # ─── ChannelAdapter interface ─────────────────────────────────────────────

    async def connect(self) -> None:
        """Start the aiogram long-polling loop as a background asyncio task."""
        from aiogram import Bot, Dispatcher, Router
        from aiogram.filters import Command
        from aiogram.types import Message

        self._bot = Bot(token=self._config.resolve_bot_token() or "")
        self._dp = Dispatcher()
        router = Router()

        # ── /start, /help ──────────────────────────────────────────────────

        @router.message(Command("start", "help"))
        async def _handle_start(message: Message) -> None:
            policy = self._config.dm_policy
            if policy == "pairing":
                text = (
                    "Hi! I'm Munai, your personal AI assistant.\n\n"
                    "To start chatting, ask your admin for a pairing code, "
                    "then send:\n  /pair <code>\n\n"
                    "Once paired, just send me any message."
                )
            elif policy == "open":
                text = "Hi! I'm Munai. Send me any message to start chatting."
            else:
                text = "This bot is not currently accepting messages."
            await message.reply(text)

        # ── /pair <code> ───────────────────────────────────────────────────

        @router.message(Command("pair"))
        async def _handle_pair(message: Message) -> None:
            if message.from_user is None:
                return
            user_id = str(message.from_user.id)
            args = (message.text or "").split(maxsplit=1)
            code = args[1].strip() if len(args) > 1 else ""

            if not code:
                await message.reply("Usage: /pair <code>")
                return

            if self._pairing.verify_and_approve(code, user_id):
                await message.reply(
                    "Paired! You can now chat with Munai. Send any message to begin."
                )
                await self._audit.log(
                    "telegram.pairing_success",
                    detail={"user_id": user_id},
                )
            else:
                await message.reply("Invalid or expired pairing code. Try again.")
                await self._audit.log(
                    "telegram.pairing_fail",
                    detail={"user_id": user_id},
                )

        # ── Regular text messages ──────────────────────────────────────────

        @router.message()
        async def _handle_message(message: Message) -> None:
            if message.from_user is None or not message.text:
                return

            user_id = str(message.from_user.id)
            chat_id = message.chat.id
            text = message.text.strip()

            # Policy check
            if not self._is_authorized(user_id):
                if self._config.dm_policy == "closed":
                    await message.reply("This bot is not accepting messages.")
                elif self._config.dm_policy == "pairing":
                    await message.reply(
                        "You need to pair first. Ask your admin for a code, "
                        "then send: /pair <code>"
                    )
                else:
                    # open policy — should be authorized, but handle edge case
                    await message.reply("Access denied.")
                return

            session_key = f"telegram:{user_id}"
            session_id = self._session_router.get_or_create_session(session_key)
            emit_fn = self._make_emit_fn(chat_id)

            await self._audit.log(
                "channel.message_in",
                detail={"text_length": len(text), "channel": "telegram"},
                session_id=session_id,
                channel="telegram",
            )

            async def work() -> None:
                await self._runtime.run_turn(
                    session_id=session_id,
                    channel="telegram",
                    sender_id=user_id,
                    text=text,
                    emit=emit_fn,
                )

            await self._lane_queue.submit(session_key, work)

        self._dp.include_router(router)
        self._poll_task = asyncio.create_task(
            self._dp.start_polling(self._bot, handle_signals=False),
            name="telegram-polling",
        )
        log.info("Telegram adapter started (dm_policy=%s)", self._config.dm_policy)

    async def disconnect(self) -> None:
        """Cancel the polling loop and close the bot HTTP session."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._bot:
            try:
                await self._bot.session.close()
            except Exception:
                pass
        log.info("Telegram adapter stopped")

    # ─── Public helpers ───────────────────────────────────────────────────────

    async def send_message(self, chat_id: int | str, text: str) -> None:
        """Send text to a Telegram chat, splitting at the 4096-char limit."""
        if not self._bot or not text:
            return
        for chunk in _split_text(text, _TELEGRAM_MAX_CHARS):
            try:
                await self._bot.send_message(chat_id, chunk)
            except Exception as exc:
                log.warning("Failed to send Telegram message to %s: %s", chat_id, exc)

    async def send_to_owner(self, text: str) -> int:
        """Send text to all paired users (the "owner" abstraction).

        Returns the number of users the message was delivered to.
        """
        users = self._pairing.get_allowed_users()
        for uid in users:
            await self.send_message(uid, text)
        return len(users)

    def make_emit_fn(self, chat_id: int | str):
        """Return an emit callback for use in AgentRuntime.run_turn()."""
        return self._make_emit_fn(chat_id)

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _is_authorized(self, user_id: str) -> bool:
        """Check if user_id is allowed to chat."""
        if self._config.dm_policy == "open":
            return True
        if self._config.dm_policy == "closed":
            return False
        # pairing mode: allowed if in pairing list OR in static allow_from
        return self._pairing.is_allowed(user_id) or user_id in self._config.allow_from

    def _make_emit_fn(self, chat_id: int | str):
        """Build an emit callback that sends the final response to Telegram.

        - agent.done → send response text (or error text)
        - all other events → no-op (Telegram has no streaming)
        """
        async def emit(event_name: str, payload: dict[str, Any]) -> None:
            if event_name == "agent.done":
                response_text = payload.get("text", "")
                if payload.get("error") and not response_text:
                    response_text = "An error occurred."
                if response_text:
                    await self.send_message(chat_id, response_text)

        return emit


def _split_text(text: str, limit: int) -> list[str]:
    """Split text into chunks of at most `limit` characters."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
