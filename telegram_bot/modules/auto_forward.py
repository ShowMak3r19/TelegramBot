from __future__ import annotations

import logging
import html
from dataclasses import asdict
from typing import Any

from telegram_bot.config import AutoForwardConfig
from telegram_bot.shared.telegram_io import safe_delete_message, safe_edit_message
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)


class AutoForwardModule:
    def __init__(self, card: ModuleCard, config: AutoForwardConfig) -> None:
        self.card = card
        self.config = config
        self._sync_card_config()

    async def start(self) -> None:
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        message = _event_message(event)
        text = _message_text(message)
        mode = match_auto_forward_mode(text, self.config)
        if mode is None:
            return HandlerResult.ignored(self.card.id)

        if self.config.delete_command:
            await safe_delete_message(message, "auto_forward_command")

        if not getattr(message, "is_reply", False):
            await _send_text(event, "\u8bf7\u56de\u590d\u4e00\u6761\u6d88\u606f\u540e\u518d\u53d1\u9001\u8f6c\u53d1\u547d\u4ee4\u3002", parse_mode="html")
            return HandlerResult.handled(self.card.id, "auto forward missing reply")

        replied = await _get_reply_message(message)
        if replied is None:
            await _send_text(event, "\u672a\u80fd\u8bfb\u53d6\u88ab\u5f15\u7528\u6d88\u606f\u3002", parse_mode="html")
            return HandlerResult.handled(self.card.id, "auto forward reply unavailable")

        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        client = getattr(event, "client", None)
        if mode == "native":
            if client is None or chat_id is None or not hasattr(client, "forward_messages"):
                logger.warning("Auto forward skipped because Telegram client cannot forward messages")
                return HandlerResult.failed(self.card.id, "Telegram client cannot forward messages")
            await client.forward_messages(chat_id, replied)
        elif mode == "copy_text":
            if client is None or chat_id is None or not hasattr(client, "send_message"):
                logger.warning("Auto forward skipped because Telegram client cannot send messages")
                return HandlerResult.failed(self.card.id, "Telegram client cannot send messages")
            content = _message_text(replied).strip()
            if not content:
                await _send_text(event, "\u590d\u5236\u6587\u672c\u6a21\u5f0f\u53ea\u80fd\u5904\u7406\u6709\u6587\u672c\u7684\u6d88\u606f\u3002", parse_mode="html")
                return HandlerResult.handled(self.card.id, "auto forward copy text unavailable", {"mode": mode})
            await client.send_message(chat_id, content)
        elif mode == "quote":
            if client is None or chat_id is None or not hasattr(client, "send_message"):
                logger.warning("Auto forward skipped because Telegram client cannot send messages")
                return HandlerResult.failed(self.card.id, "Telegram client cannot send messages")
            await client.send_message(chat_id, await _format_quote_message(replied), parse_mode="html")
        elif mode == "link":
            if client is None or chat_id is None or not hasattr(client, "send_message"):
                logger.warning("Auto forward skipped because Telegram client cannot send messages")
                return HandlerResult.failed(self.card.id, "Telegram client cannot send messages")
            link = await _public_message_link(event, replied)
            if not link:
                await _send_text(event, "\u8fd9\u6761\u6d88\u606f\u6ca1\u6709\u516c\u5f00\u53ef\u70b9\u51fb\u94fe\u63a5\u3002", parse_mode="html")
                return HandlerResult.handled(self.card.id, "auto forward link unavailable", {"mode": mode})
            await client.send_message(chat_id, link)
        else:
            return HandlerResult.ignored(self.card.id)

        logger.info(
            "Auto forward handled: mode=%s chat_id=%s command_message_id=%s replied_message_id=%s",
            mode,
            chat_id,
            getattr(message, "id", ""),
            getattr(replied, "id", ""),
        )
        return HandlerResult.handled(
            self.card.id,
            "auto forwarded message",
            {
                "chat_id": str(chat_id),
                "message_id": str(getattr(replied, "id", "")),
                "mode": mode,
            },
        )

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("auto_forward", values)
        if not isinstance(data, dict):
            return
        self.config = auto_forward_config_from_dict({**asdict(self.config), **data})
        self._sync_card_config()

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)


def auto_forward_config_from_dict(data: dict[str, Any]) -> AutoForwardConfig:
    defaults = AutoForwardConfig()
    return AutoForwardConfig(
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        copy_text_command_prefixes=_list_or_default(data.get("copy_text_command_prefixes"), defaults.copy_text_command_prefixes),
        quote_command_prefixes=_list_or_default(data.get("quote_command_prefixes"), defaults.quote_command_prefixes),
        link_command_prefixes=_list_or_default(data.get("link_command_prefixes"), defaults.link_command_prefixes),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
    )


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or list(default)


def match_auto_forward_mode(text: str, config: AutoForwardConfig) -> str | None:
    normalized = (text or "").strip()
    checks = (
        ("native", config.command_prefixes),
        ("copy_text", config.copy_text_command_prefixes),
        ("quote", config.quote_command_prefixes),
        ("link", config.link_command_prefixes),
    )
    for mode, prefixes in checks:
        if is_auto_forward_command(normalized, prefixes):
            return mode
    return None


def is_auto_forward_command(text: str, prefixes: list[str]) -> bool:
    normalized = (text or "").strip()
    return any(normalized == prefix.strip() for prefix in prefixes if prefix.strip())


def _event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def _message_text(message: Any) -> str:
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, None)
        if value:
            return str(value)
    return ""


def _is_outgoing(event: Any) -> bool:
    message = _event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


async def _get_reply_message(message: Any) -> Any:
    if message is None or not getattr(message, "is_reply", False) or not hasattr(message, "get_reply_message"):
        return None
    return await message.get_reply_message()


async def _send_text(event: Any, text: str, parse_mode: str | None = None) -> Any:
    message = _event_message(event)
    client = getattr(event, "client", None)
    chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
    if client is not None and chat_id is not None and hasattr(client, "send_message"):
        kwargs = {}
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        return await client.send_message(chat_id, text, **kwargs)
    return None


async def _format_quote_message(message: Any) -> str:
    sender = await _sender_display_name(message)
    content = _message_text(message).strip() or "\u975e\u6587\u672c\u6d88\u606f"
    return f"\u6765\u81ea {html.escape(sender)}\n<blockquote expandable>{html.escape(content)}</blockquote>"


async def _sender_display_name(message: Any) -> str:
    sender = getattr(message, "sender", None)
    if sender is None and hasattr(message, "get_sender"):
        try:
            sender = await message.get_sender()
        except Exception:
            sender = None
    if sender is None:
        sender_id = getattr(message, "sender_id", "")
        return str(sender_id or "\u672a\u77e5\u7528\u6237")
    username = getattr(sender, "username", "") or ""
    first_name = getattr(sender, "first_name", "") or ""
    last_name = getattr(sender, "last_name", "") or ""
    title = getattr(sender, "title", "") or ""
    name = " ".join(part for part in (first_name, last_name) if part).strip() or title
    if username and name:
        return f"{name} (@{username})"
    if username:
        return f"@{username}"
    return name or str(getattr(sender, "id", "") or "\u672a\u77e5\u7528\u6237")


async def _public_message_link(event: Any, message: Any) -> str | None:
    username = await _chat_username(message)
    if not username:
        username = await _chat_username(event)
    if not username:
        return None
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    return f"https://t.me/{username.lstrip('@')}/{message_id}"


async def _chat_username(source: Any) -> str:
    chat = getattr(source, "chat", None)
    if chat is None and hasattr(source, "get_chat"):
        try:
            chat = await source.get_chat()
        except Exception:
            chat = None
    if chat is None:
        return ""
    return str(getattr(chat, "username", "") or "")
