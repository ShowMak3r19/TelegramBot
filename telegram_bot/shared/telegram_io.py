"""Telegram 事件解包与消息收发的共享适配层。

把原先散落在功能模块（尤其 ai_reply）里的事件/消息工具集中到这里，
让各功能模块通过稳定接口复用，而不是互相 import。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_SAFE_TEXT_LIMIT = 3600
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def is_edited_event(event: Any) -> bool:
    if bool(getattr(event, "_tgbot_edited", False)):
        return True
    cls_name = f"{type(event).__qualname__} {type(event).__name__}"
    return "MessageEdited" in cls_name


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            fh.write(content)
            fh.flush()
        os.replace(tmp_path, target)
    except BaseException:
        if tmp_path is not None:
            unlink_quietly(tmp_path)
        raise


def prune_dir_files(directory: Path, *, max_files: int = 200, keep_names: set[str] | None = None) -> int:
    """保留目录下最新的 max_files 个普通文件，避免生成媒体无限堆积。"""
    if max_files <= 0 or not directory.exists() or not directory.is_dir():
        return 0
    keep = keep_names or set()
    try:
        files = [item for item in directory.iterdir() if item.is_file() and not item.name.startswith(".")]
    except OSError:
        return 0
    if len(files) <= max_files:
        return 0
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    removed = 0
    for stale in files[max_files:]:
        if stale.name in keep:
            continue
        unlink_quietly(stale)
        removed += 1
    return removed


def safe_filename_component(value: str, fallback: str = "item", max_length: int = 80) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned[:max_length]


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
        logger.warning("Failed to edit message, retrying with truncated plain text: %s", exc)
    fallback_text = _HTML_TAG_RE.sub("", text) if parse_mode == "html" else text
    fallback_mode = None if parse_mode == "html" else parse_mode
    try:
        await message.edit(truncate_text(fallback_text, 3000), parse_mode=fallback_mode, **kwargs)
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
