"""quote-api 适配层：把消息数据渲染成语录贴纸。

把对 quote-api 服务的依赖隔离在这里，功能模块只通过本模块通信，便于替换/自建。
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from telegram_bot.shared.net import ensure_http_url

logger = logging.getLogger(__name__)

# Telethon 消息实体类名 → quote-api 类型（用类名判断，避免硬依赖 telethon 导入）
_ENTITY_TYPE_MAP = {
    "MessageEntityBold": "bold",
    "MessageEntityItalic": "italic",
    "MessageEntityUnderline": "underline",
    "MessageEntityStrike": "strikethrough",
    "MessageEntityCode": "code",
    "MessageEntityPre": "pre",
    "MessageEntityUrl": "url",
    "MessageEntityMention": "mention",
    "MessageEntityHashtag": "hashtag",
    "MessageEntityCashtag": "cashtag",
    "MessageEntityBotCommand": "bot_command",
    "MessageEntityEmail": "email",
    "MessageEntityPhone": "phone_number",
    "MessageEntitySpoiler": "spoiler",
}


def convert_entities(entities: Any) -> list[dict[str, Any]]:
    """把 Telethon 消息实体转换为 quote-api 期望的格式。"""
    result: list[dict[str, Any]] = []
    for entity in entities or []:
        base: dict[str, Any] = {
            "offset": int(getattr(entity, "offset", 0) or 0),
            "length": int(getattr(entity, "length", 0) or 0),
        }
        cls = entity.__class__.__name__
        mapped = _ENTITY_TYPE_MAP.get(cls)
        if mapped:
            base["type"] = mapped
        elif cls == "MessageEntityTextUrl":
            base["type"] = "text_link"
            base["url"] = str(getattr(entity, "url", "") or "")
        elif cls == "MessageEntityCustomEmoji":
            document_id = getattr(entity, "document_id", None)
            base["type"] = "custom_emoji"
            base["custom_emoji_id"] = str(document_id) if document_id is not None else ""
        elif cls == "MessageEntityMentionName":
            base["type"] = "text_mention"
            base["user"] = {"id": getattr(entity, "user_id", None)}
        result.append(base)
    return result


def build_quote_payload(messages: list[dict[str, Any]], config: Any) -> dict[str, Any]:
    return {
        "type": "quote",
        "format": "webp",
        "backgroundColor": config.background_color,
        "width": int(config.width),
        "height": int(config.height),
        "scale": int(config.scale),
        "emojiBrand": config.emoji_brand,
        "messages": messages,
    }


def generate_quote_sync(api_url: str, payload: dict[str, Any], timeout: float) -> bytes:
    """同步 POST quote-api，返回图片字节。请在 asyncio.to_thread 中调用以免阻塞事件循环。"""
    url = ensure_http_url(api_url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "TeleBox/0.2.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# ---- 返回内容的格式检测：决定按静态还是动态贴纸发送 ----


def is_webm(buffer: bytes) -> bool:
    return len(buffer) >= 4 and buffer[0:4] == b"\x1a\x45\xdf\xa3"


def is_gzip_tgs(buffer: bytes) -> bool:
    return len(buffer) >= 2 and buffer[0] == 0x1F and buffer[1] == 0x8B


def is_mp4(buffer: bytes) -> bool:
    return len(buffer) >= 12 and buffer[4:8] == b"ftyp"


def is_animated_webp(buffer: bytes) -> bool:
    if len(buffer) < 12 or buffer[0:4] != b"RIFF" or buffer[8:12] != b"WEBP":
        return False
    return b"ANIM" in buffer[12:]


def webp_dimensions(buffer: bytes, default: tuple[int, int] = (512, 768)) -> tuple[int, int]:
    try:
        if is_webm(buffer):
            return 512, 512
        if len(buffer) < 30 or buffer[0:4] != b"RIFF" or buffer[8:12] != b"WEBP":
            return default
        chunk = buffer[12:16]
        if chunk == b"VP8 ":
            width = int.from_bytes(buffer[26:28], "little") & 0x3FFF
            height = int.from_bytes(buffer[28:30], "little") & 0x3FFF
            return width or default[0], height or default[1]
        if chunk == b"VP8L":
            data = int.from_bytes(buffer[21:25], "little")
            width = (data & 0x3FFF) + 1
            height = ((data >> 14) & 0x3FFF) + 1
            return width, height
        if chunk == b"VP8X":
            width = (int.from_bytes(buffer[24:27], "little") & 0xFFFFFF) + 1
            height = (int.from_bytes(buffer[27:30], "little") & 0xFFFFFF) + 1
            return width, height
    except Exception:
        return default
    return default
