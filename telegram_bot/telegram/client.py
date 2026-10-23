from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot.config import TelegramConfig

logger = logging.getLogger(__name__)
MessageCallback = Callable[[Any], Awaitable[None]]
_PROGRAMMATIC_MESSAGE_HISTORY_LIMIT = 1024
_TRACKED_CLIENT_METHODS = ("send_message", "send_file", "forward_messages", "edit_message")


@dataclass(frozen=True)
class _PendingProgrammaticOperation:
    token: int
    method_name: str
    target: str | None
    text: str | None


class ProgrammaticMessageTracker:
    """Tracks outgoing messages created through Telegram client APIs."""

    def __init__(self, history_limit: int = _PROGRAMMATIC_MESSAGE_HISTORY_LIMIT) -> None:
        self.history_limit = max(1, history_limit)
        self._keys: set[tuple[str, str]] = set()
        self._history: deque[tuple[str, str]] = deque()
        self._pending: dict[int, _PendingProgrammaticOperation] = {}
        self._next_token = 0

    def begin(self, method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> int:
        self._next_token += 1
        target = _operation_target(args, kwargs)
        text = _operation_text(method_name, args, kwargs)
        self._pending[self._next_token] = _PendingProgrammaticOperation(
            self._next_token,
            method_name,
            target,
            text,
        )
        return self._next_token

    def finish(self, token: int, result: Any) -> None:
        pending = self._pending.pop(token, None)
        if pending is not None:
            self._remember_result(result, pending.target)

    def cancel(self, token: int) -> None:
        self._pending.pop(token, None)

    def is_programmatic(self, message: Any) -> bool:
        key = _message_key(message)
        if key is not None and key in self._keys:
            return True

        chat_id = _message_chat_id(message)
        text = _message_text(message)
        for pending in self._pending.values():
            if pending.target is not None and chat_id != pending.target:
                continue
            if not _pending_operation_matches_message(pending, message, text):
                continue
            if key is not None:
                self._remember(key)
            return True
        return False

    def _remember_result(self, result: Any, fallback_chat_id: str | None) -> None:
        if isinstance(result, (list, tuple)):
            for item in result:
                self._remember_result(item, fallback_chat_id)
            return
        message_id = getattr(result, "id", None)
        if message_id is None:
            return
        chat_id = _message_chat_id(result) or fallback_chat_id
        if chat_id is not None:
            self._remember((chat_id, str(message_id)))

    def _remember(self, key: tuple[str, str]) -> None:
        if key in self._keys:
            return
        self._keys.add(key)
        self._history.append(key)
        while len(self._history) > self.history_limit:
            self._keys.discard(self._history.popleft())


class TelegramAdapter:
    def __init__(self, config: TelegramConfig, project_root: Path, callback: MessageCallback) -> None:
        self.config = config
        self.project_root = project_root
        self.callback = callback
        self.client: Any | None = None
        self._programmatic_messages = ProgrammaticMessageTracker()
        self.connected = False
        self.last_error = ""

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("Telegram adapter disabled by config")
            return
        if not self.config.api_id or not self.config.api_hash:
            self.last_error = "Telegram api_id/api_hash are not configured"
            logger.warning(self.last_error)
            return

        try:
            import telethon
            from telethon import TelegramClient, events
        except ImportError as exc:
            self.last_error = "Telethon is not installed"
            logger.error("%s: %s", self.last_error, exc)
            return

        rich_messages_available = hasattr(getattr(telethon, "types", None), "InputRichMessageMarkdown")
        logger.info(
            "Telethon runtime loaded: version=%s rich_messages=%s",
            getattr(telethon, "__version__", "unknown"),
            rich_messages_available,
        )
        if not rich_messages_available:
            logger.warning(
                "Telegram Rich Messages are unavailable in this Telethon runtime. "
                "Run ./nas-conda-setup.sh and restart the process."
            )

        session_dir = Path(self.config.session_dir)
        if not session_dir.is_absolute():
            session_dir = self.project_root / session_dir
        session_dir.mkdir(parents=True, exist_ok=True)
        session_path = session_dir / self.config.session_name

        self.client = TelegramClient(str(session_path), self.config.api_id, self.config.api_hash)
        self._install_programmatic_message_tracking()

        @self.client.on(events.NewMessage)
        async def _on_message(event: Any) -> None:
            await self._handle_monitored_event(event, "message")

        @self.client.on(events.MessageEdited)
        async def _on_message_edited(event: Any) -> None:
            await self._handle_monitored_event(event, "edited message")

        if self.config.bot_token:
            await self.client.start(bot_token=self.config.bot_token)
        else:
            await self.client.start()
        self.connected = True
        logger.info("Telegram adapter connected")

    async def _handle_monitored_event(self, event: Any, event_name: str) -> None:
        if self._should_monitor(event):
            self._log_monitored_message(event, event_name)
            await self.callback(event)

    async def stop(self) -> None:
        if self.client is not None:
            await self.client.disconnect()
        self.connected = False
        logger.info("Telegram adapter stopped")

    async def list_groups(self) -> list[dict[str, Any]]:
        if not self.client or not self.connected:
            raise RuntimeError("Telegram client is not connected")

        selected = {str(item).strip() for item in self.config.monitored_groups if str(item).strip()}
        groups: list[dict[str, Any]] = []
        dialogs = await self.client.get_dialogs()
        for dialog in dialogs:
            entity = dialog.entity
            is_group = bool(getattr(dialog, "is_group", False))
            is_channel = bool(getattr(dialog, "is_channel", False))
            megagroup = bool(getattr(entity, "megagroup", False))
            broadcast = bool(getattr(entity, "broadcast", False))
            if not (is_group or megagroup or broadcast):
                continue

            chat_id = str(getattr(entity, "id", getattr(dialog, "id", "")))
            if chat_id and not chat_id.startswith("-100") and (is_channel or megagroup or broadcast):
                chat_id = f"-100{chat_id}"
            username = getattr(entity, "username", "") or ""
            targets = {chat_id}
            if username:
                targets.add(username)
                targets.add(f"@{username}")
            groups.append(
                {
                    "id": chat_id,
                    "title": getattr(dialog, "title", "") or chat_id,
                    "username": username,
                    "kind": "channel" if broadcast else "group",
                    "megagroup": megagroup,
                    "broadcast": broadcast,
                    "selected": bool(selected & targets),
                }
            )
        groups.sort(key=lambda item: item["title"].lower())
        return groups

    async def list_targets(self) -> list[dict[str, Any]]:
        if not self.client or not self.connected:
            raise RuntimeError("Telegram client is not connected")

        selected = {str(item).strip() for item in self.config.monitored_groups if str(item).strip()}
        targets: list[dict[str, Any]] = []
        dialogs = await self.client.get_dialogs()
        for dialog in dialogs:
            entity = dialog.entity
            is_group = bool(getattr(dialog, "is_group", False))
            is_channel = bool(getattr(dialog, "is_channel", False))
            megagroup = bool(getattr(entity, "megagroup", False))
            broadcast = bool(getattr(entity, "broadcast", False))
            is_bot = bool(getattr(entity, "bot", False))
            if not (is_group or megagroup or broadcast or is_bot):
                continue

            target_id = str(getattr(entity, "id", getattr(dialog, "id", "")))
            if target_id and not target_id.startswith("-100") and (is_channel or megagroup or broadcast):
                target_id = f"-100{target_id}"
            username = getattr(entity, "username", "") or ""
            aliases = {target_id}
            if username:
                aliases.add(username)
                aliases.add(f"@{username}")
            targets.append(
                {
                    "id": target_id,
                    "title": getattr(dialog, "title", "") or username or target_id,
                    "username": username,
                    "kind": "bot" if is_bot else "channel" if broadcast else "group",
                    "selected": bool(selected & aliases),
                }
            )
        targets.sort(key=lambda item: item["title"].lower())
        return targets

    async def send_message(self, target: str, text: str, parse_mode: str | None = None) -> Any:
        if not self.client or not self.connected:
            raise RuntimeError("Telegram client is not connected")
        entity: Any = target.strip()
        if _looks_like_int(entity):
            entity = int(entity)
        message = await self.client.send_message(entity, text, parse_mode=parse_mode)
        logger.info("Telegram message sent: target=%s text=%s", target, _preview_text(text, 120))
        return message

    async def iter_history_messages(self, target: str, *, min_id: int = 0) -> AsyncIterator[Any]:
        """Yield a chat's history oldest-first, strictly newer than ``min_id``."""
        if not self.client or not self.connected:
            raise RuntimeError("Telegram client is not connected")
        entity: Any = target.strip()
        if _looks_like_int(entity):
            entity = int(entity)
        async for message in self.client.iter_messages(
            entity,
            min_id=max(0, int(min_id)),
            reverse=True,
        ):
            yield message

    def is_programmatic_message(self, message: Any) -> bool:
        return self._programmatic_messages.is_programmatic(message)

    def _install_programmatic_message_tracking(self) -> None:
        if self.client is None:
            return
        for method_name in _TRACKED_CLIENT_METHODS:
            original = getattr(self.client, method_name, None)
            if not callable(original):
                continue

            async def tracked_call(
                *args: Any,
                __method_name: str = method_name,
                __original: Callable[..., Awaitable[Any]] = original,
                **kwargs: Any,
            ) -> Any:
                token = self._programmatic_messages.begin(__method_name, args, kwargs)
                try:
                    result = await __original(*args, **kwargs)
                except BaseException:
                    self._programmatic_messages.cancel(token)
                    raise
                self._programmatic_messages.finish(token, result)
                return result

            setattr(self.client, method_name, tracked_call)

    def update_monitored_groups(self, groups: list[str], group_meta: dict[str, Any] | None = None) -> None:
        self.config.monitored_groups = [str(item).strip() for item in groups if str(item).strip()]
        if isinstance(group_meta, dict):
            self.config.monitored_group_meta = _clean_group_meta(group_meta, self.config.monitored_groups)
        logger.info("Telegram monitored groups updated: %s selected", len(self.config.monitored_groups))

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "connected": self.connected,
            "session_name": self.config.session_name,
            "monitored_groups": self.config.monitored_groups,
            "last_error": self.last_error,
        }

    def _should_monitor(self, event: Any) -> bool:
        groups = [str(item).strip() for item in self.config.monitored_groups if str(item).strip()]
        if not groups:
            return True
        chat_id = str(getattr(event, "chat_id", ""))
        return chat_id in groups

    def _log_monitored_message(self, event: Any, event_name: str = "message") -> None:
        message = getattr(event, "message", event)
        chat_id = getattr(event, "chat_id", getattr(message, "chat_id", ""))
        message_id = getattr(message, "id", "")
        sender_id = getattr(message, "sender_id", getattr(event, "sender_id", ""))
        text = _preview_message_text(message)
        has_media = bool(getattr(message, "media", None))
        logger.info(
            "Monitored Telegram %s: chat_id=%s sender_id=%s message_id=%s out=%s media=%s text=%s",
            event_name,
            chat_id,
            sender_id,
            message_id,
            bool(getattr(message, "out", False)),
            has_media,
            text,
        )


def _preview_message_text(message: Any, limit: int = 240) -> str:
    text = str(getattr(message, "raw_text", getattr(message, "message", "")) or "")
    return _preview_text(text, limit) or "[no text]"


def _preview_text(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _clean_group_meta(group_meta: dict[str, Any], selected_groups: list[str]) -> dict[str, dict[str, str]]:
    selected = {str(item).strip() for item in selected_groups if str(item).strip()}
    cleaned: dict[str, dict[str, str]] = {}
    for group_id in selected:
        raw = group_meta.get(group_id)
        if not isinstance(raw, dict):
            continue
        cleaned[group_id] = {
            "title": str(raw.get("title") or group_id).strip(),
            "username": str(raw.get("username") or "").strip(),
            "kind": str(raw.get("kind") or "group").strip(),
        }
    return cleaned


def _looks_like_int(value: str) -> bool:
    return value.startswith("-") and value[1:].isdigit() or value.isdigit()


def _operation_target(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    target = args[0] if args else kwargs.get("entity")
    return _normalise_chat_id(target)


def _operation_text(method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    value: Any = None
    if method_name == "send_message":
        value = args[1] if len(args) > 1 else kwargs.get("message")
    elif method_name == "send_file":
        value = kwargs.get("caption")
    elif method_name == "edit_message":
        value = args[2] if len(args) > 2 else kwargs.get("text")
    if value is None or not isinstance(value, str):
        return None
    return value


def _message_key(message: Any) -> tuple[str, str] | None:
    chat_id = _message_chat_id(message)
    message_id = getattr(message, "id", None)
    if chat_id is None or message_id is None:
        return None
    return chat_id, str(message_id)


def _message_chat_id(message: Any) -> str | None:
    return _normalise_chat_id(getattr(message, "chat_id", None))


def _message_text(message: Any) -> str:
    return str(getattr(message, "raw_text", getattr(message, "message", "")) or "")


def _pending_operation_matches_message(
    pending: _PendingProgrammaticOperation,
    message: Any,
    text: str,
) -> bool:
    if pending.method_name == "send_file":
        if pending.text is None or getattr(message, "media", None) is None:
            return False
        return text == pending.text
    if pending.method_name == "forward_messages":
        return False
    return pending.text is not None and text == pending.text


def _normalise_chat_id(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if _looks_like_int(stripped) else None
    return None
