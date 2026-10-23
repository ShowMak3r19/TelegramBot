from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram_bot.config import ChatHistoryConfig, TelegramConfig
from telegram_bot.persistence import ChatHistoryStore

logger = logging.getLogger(__name__)


class ChatHistoryBackfillJob:
    """Resumable, text-only history import for configured Telegram chats."""

    def __init__(
        self,
        config: ChatHistoryConfig,
        telegram_config: TelegramConfig,
        telegram: Any,
        store: ChatHistoryStore,
    ) -> None:
        self.config = config
        self.telegram_config = telegram_config
        self.telegram = telegram
        self.store = store
        self._task: asyncio.Task[None] | None = None
        self.current_chat_id = ""
        self.scanned_messages = 0
        self.stored_messages = 0
        self.last_error = ""

    async def start(self) -> None:
        if not self.config.enabled or not self.config.backfill_enabled:
            logger.info("Chat history backfill disabled by config")
            return
        if not getattr(self.telegram, "connected", False):
            logger.warning("Chat history backfill skipped because Telegram is not connected")
            return
        if self._task is not None and not self._task.done():
            return
        groups = self._monitored_groups()
        if not groups:
            logger.info("Chat history backfill skipped because no monitored groups are configured")
            return
        self._task = asyncio.create_task(self._run(groups), name="chat-history-backfill")
        logger.info("Chat history backfill scheduled: groups=%s", len(groups))

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Chat history backfill stopped")

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled and self.config.backfill_enabled,
            "running": self._task is not None and not self._task.done(),
            "current_chat_id": self.current_chat_id,
            "scanned_messages": self.scanned_messages,
            "stored_messages": self.stored_messages,
            "last_error": self.last_error,
        }

    async def _run(self, groups: list[str]) -> None:
        try:
            for chat_id in groups:
                self.current_chat_id = chat_id
                try:
                    await self._backfill_chat(chat_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = str(exc)
                    await asyncio.to_thread(self.store.mark_backfill_failed, chat_id, str(exc))
                    logger.exception("Chat history backfill failed: chat_id=%s", chat_id)
        finally:
            self.current_chat_id = ""

    async def _backfill_chat(self, chat_id: str) -> None:
        state = await asyncio.to_thread(self.store.get_backfill_state, chat_id)
        checkpoint = state.last_message_id if state is not None else 0
        await asyncio.to_thread(self.store.mark_backfill_started, chat_id)
        batch_size = max(1, int(self.config.backfill_batch_size))
        batch: list[Any] = []
        last_message_id = checkpoint
        scanned_for_chat = 0
        stored_for_chat = 0
        logger.info(
            "Chat history backfill started: chat_id=%s min_id=%s batch_size=%s",
            chat_id,
            checkpoint,
            batch_size,
        )

        async for message in self.telegram.iter_history_messages(chat_id, min_id=checkpoint):
            batch.append(message)
            message_id = _message_id(message)
            if message_id is not None:
                last_message_id = max(last_message_id, message_id)
            if len(batch) >= batch_size:
                stored = await self._flush_batch(chat_id, batch, last_message_id)
                scanned_for_chat += len(batch)
                stored_for_chat += stored
                batch = []

        if batch:
            stored = await self._flush_batch(chat_id, batch, last_message_id)
            scanned_for_chat += len(batch)
            stored_for_chat += stored

        await asyncio.to_thread(self.store.mark_backfill_complete, chat_id, last_message_id)
        self.last_error = ""
        logger.info(
            "Chat history backfill completed: chat_id=%s checkpoint=%s scanned=%s stored_text=%s",
            chat_id,
            last_message_id,
            scanned_for_chat,
            stored_for_chat,
        )

    async def _flush_batch(self, chat_id: str, batch: list[Any], last_message_id: int) -> int:
        stored = await asyncio.to_thread(
            self.store.record_events,
            batch,
            fallback_chat_id=chat_id,
        )
        await asyncio.to_thread(
            self.store.update_backfill_progress,
            chat_id,
            last_message_id,
            scanned_messages=len(batch),
            stored_messages=stored,
        )
        self.scanned_messages += len(batch)
        self.stored_messages += stored
        logger.info(
            "Chat history backfill progress: chat_id=%s checkpoint=%s scanned_total=%s stored_text_total=%s",
            chat_id,
            last_message_id,
            self.scanned_messages,
            self.stored_messages,
        )
        return stored

    def _monitored_groups(self) -> list[str]:
        groups: list[str] = []
        for value in self.telegram_config.monitored_groups:
            chat_id = str(value).strip()
            if chat_id and chat_id not in groups:
                groups.append(chat_id)
        return groups


def _message_id(message: Any) -> int | None:
    try:
        value = int(getattr(message, "id", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None
