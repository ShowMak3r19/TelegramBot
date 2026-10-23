"""Telegram 事件解包与消息收发的共享适配层。

把原先散落在功能模块（尤其 ai_reply）里的事件/消息工具集中到这里，
让各功能模块通过稳定接口复用，而不是互相 import。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_SAFE_TEXT_LIMIT = 3600


def event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def message_text(message: Any) -> str:
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, "")
        if isinstance(value, str):
            return value.strip()
    return ""


def is_outgoing(event: Any) -> bool:
    message = event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


def sender_id(message: Any) -> Any:
    return getattr(message, "sender_id", None)


async def get_reply_message(message: Any) -> Any:
    if message is None or not getattr(message, "is_reply", False) or not hasattr(message, "get_reply_message"):
        return None
    try:
        return await message.get_reply_message()
    except Exception:
        logger.exception("Failed to load replied message")
        return None


def obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def truncate_text(value: str, limit: int = TELEGRAM_SAFE_TEXT_LIMIT) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n\n...内容过长，已自动截断"


async def safe_edit_message(message: Any, text: str, parse_mode: str | None = "html", **kwargs: Any) -> bool:
    if message is None or not hasattr(message, "edit"):
        return False
    try:
        await message.edit(text, parse_mode=parse_mode, **kwargs)
        return True
    except Exception as exc:
        logger.warning("Failed to edit message, retrying with truncated text: %s", exc)
    try:
        await message.edit(truncate_text(text, 3000), parse_mode=parse_mode)
        return True
    except Exception:
        logger.exception("Failed to edit message after retry")
        return False


async def safe_delete_message(message: Any, reason: str = "") -> bool:
    if message is None or not hasattr(message, "delete"):
        return False
    for attempt in range(2):
        try:
            await message.delete()
            return True
        except Exception as exc:
            if attempt == 0:
                logger.warning("delete message failed; retrying. reason=%s error=%s", reason, exc)
                await asyncio.sleep(0.3)
    return False


def unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
