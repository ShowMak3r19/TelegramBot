from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import QuoteConfig
from telegram_bot.shared import quote_api, telegram_media
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.telegram_io import (
    event_message,
    get_reply_message,
    is_outgoing,
    message_text,
    safe_delete_message,
    safe_edit_message,
    unlink_quietly,
)

from .base import ModuleCard

logger = logging.getLogger(__name__)

try:  # telethon 是可选运行时依赖，发送贴纸/操作贴纸包时才需要
    from telethon.tl import types as tl_types, functions as tl_functions
except ImportError:  # pragma: no cover
    tl_types = None
    tl_functions = None

STICKER_EMOJI = "📝"


class QuoteModule:
    def __init__(self, card: ModuleCard, config: QuoteConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.tmp_dir = self._resolve_path(self.config.tmp_dir)
        self._sync_card_config()

    async def start(self) -> None:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not is_outgoing(event):
            return HandlerResult.ignored(self.card.id)
        message = event_message(event)
        parsed = parse_quote_command(message_text(message or event), self.config.command_prefixes)
        if parsed is None:
            return HandlerResult.ignored(self.card.id)

        kind = parsed["kind"]
        try:
            if kind == "config":
                await self._handle_config(event, parsed["args"])
            elif kind == "fake":
                await self._handle_fake_quote(event, parsed["content"])
            elif kind == "save":
                await self._handle_save_sticker(event)
            else:
                await self._handle_generate(event, parsed["count"], parsed["with_reply"])
        except Exception as exc:
            logger.exception("Quote generation failed: %s", exc)
            await safe_edit_message(message, f"语录生成失败：{html.escape(str(exc))}", parse_mode="html")
            return HandlerResult.failed(self.card.id, str(exc))
        return HandlerResult.handled(self.card.id, "quote handled", {"kind": kind})

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("quote", values)
        if not isinstance(data, dict):
            return
        from telegram_bot.config import _quote_config_from_dict

        self.config = _quote_config_from_dict({**asdict(self.config), **data})
        self.tmp_dir = self._resolve_path(self.config.tmp_dir)
        self._sync_card_config()

    # ---- 生成语录 ----

    async def _handle_generate(self, event: Any, count: int, with_reply: bool) -> None:
        message = event_message(event)
        replied = await get_reply_message(message)
        if not replied:
            await safe_edit_message(message, "请回复一条消息")
            return
        count = max(1, min(int(count or 1), int(self.config.max_messages)))
        await safe_edit_message(message, "正在生成语录贴纸...")

        client = getattr(event, "client", None)
        messages = await self._collect_messages(client, replied, count)
        if not messages:
            await safe_edit_message(message, "未找到消息")
            return

        items: list[dict[str, Any]] = []
        previous_user: str | None = None
        for msg_obj in messages:
            sender = await _resolve_sender(msg_obj, client)
            if sender is None:
                continue
            selected_quote = _selected_quote_for_message(message, msg_obj)
            text = selected_quote["text"] if selected_quote else (message_text(msg_obj) or str(getattr(msg_obj, "message", "") or ""))
            entities = selected_quote["entities"] if selected_quote else (getattr(msg_obj, "entities", []) or [])
            identifier = str(getattr(sender, "id", "") or "") or str(_hash_id(_sender_display_name(sender)))
            show_avatar = identifier != previous_user
            previous_user = identifier
            item = {
                "from": await _build_quote_user(sender, client, show_avatar),
                "text": text,
                "entities": quote_api.convert_entities(entities),
                "avatar": show_avatar,
            }
            media = await _build_media(msg_obj)
            if media:
                item["media"] = media
            if with_reply:
                reply_block = await _build_reply_block(msg_obj, client)
                if reply_block:
                    item["replyMessage"] = reply_block
            items.append(item)

        if not items:
            await safe_edit_message(message, "无法获取消息发送者信息")
            return

        buffer = await self._render(items)
        if not buffer:
            await safe_edit_message(message, "生成的图片数据为空")
            return
        await self._send_quote_sticker(event, replied, buffer)
        await safe_delete_message(message, "quote_cleanup")

    async def _handle_fake_quote(self, event: Any, content: str) -> None:
        message = event_message(event)
        fake_text = (content or "").strip()
        prefix = self._primary_prefix()
        if not fake_text:
            await safe_edit_message(message, f"用法：回复他人消息后发送 <code>{html.escape(prefix)} f 内容</code>", parse_mode="html")
            return
        replied = await get_reply_message(message)
        if not replied:
            await safe_edit_message(message, "请回复或引用一条他人消息")
            return
        await safe_edit_message(message, "正在生成语录贴纸...")
        client = getattr(event, "client", None)
        sender = await _resolve_sender(replied, client)
        if sender is None:
            await safe_edit_message(message, "无法获取消息发送者信息")
            return
        items = [{
            "from": await _build_quote_user(sender, client, True),
            "text": fake_text,
            "entities": [],
            "avatar": True,
        }]
        buffer = await self._render(items)
        if not buffer:
            await safe_edit_message(message, "生成的图片数据为空")
            return
        # 假语录直接发新消息，不回复原消息
        await self._send_quote_sticker(event, None, buffer)
        await safe_delete_message(message, "quote_cleanup")

    async def _render(self, items: list[dict[str, Any]]) -> bytes:
        payload = quote_api.build_quote_payload(items, self.config)
        return await asyncio.to_thread(
            quote_api.generate_quote_sync, self.config.api_url, payload, self.config.timeout_seconds
        )

    async def _collect_messages(self, client: Any, replied: Any, count: int) -> list[Any]:
        if count <= 1 or client is None or not hasattr(client, "get_messages"):
            return [replied]
        chat_id = getattr(replied, "chat_id", None)
        reply_id = int(getattr(replied, "id", 0) or 0)
        try:
            fetched = await client.get_messages(chat_id, limit=count, offset_id=max(reply_id - 1, 0), reverse=True)
            collected = [item for item in (fetched or []) if item is not None]
            return collected or [replied]
        except Exception:
            logger.exception("收集语录消息失败")
            return [replied]

    # ---- 发送贴纸 ----

    async def _send_quote_sticker(self, event: Any, replied: Any, buffer: bytes) -> None:
        if tl_types is None:
            raise RuntimeError("缺少 telethon 依赖，无法发送贴纸")
        message = event_message(event)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        reply_to = getattr(replied, "id", None) if replied is not None else None
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        animated = quote_api.is_webm(buffer)
        ext = "webm" if animated else "webp"
        out_path = self.tmp_dir / f"quote_{chat_id}_{getattr(message, 'id', 'm')}.{ext}"
        try:
            out_path.write_bytes(buffer)
            attributes = [tl_types.DocumentAttributeSticker(alt=STICKER_EMOJI, stickerset=tl_types.InputStickerSetEmpty())]
            if not animated:
                width, height = quote_api.webp_dimensions(buffer)
                attributes.append(tl_types.DocumentAttributeImageSize(w=width, h=height))
                attributes.append(tl_types.DocumentAttributeFilename(file_name=f"sticker.{ext}"))
            await event.client.send_file(
                chat_id,
                file=str(out_path),
                attributes=attributes,
                force_document=False,
                reply_to=reply_to,
            )
        finally:
            unlink_quietly(out_path)

    # ---- 保存到贴纸包 ----

    async def _handle_save_sticker(self, event: Any) -> None:
        message = event_message(event)
        short_name = (self.config.sticker_set_short_name or "").strip()
        if not short_name:
            await safe_edit_message(
                message,
                f"❌ 未配置贴纸包，请用 <code>{html.escape(self._primary_prefix())} config sticker 名称</code> 设置",
                parse_mode="html",
            )
            return
        if tl_types is None or tl_functions is None:
            await safe_edit_message(message, "缺少 telethon 依赖，无法操作贴纸包")
            return
        replied = await get_reply_message(message)
        if not replied or not getattr(replied, "media", None):
            await safe_edit_message(message, "❌ 请回复一张贴纸或图片")
            return

        client = event.client
        document = _sticker_input_document(replied)
        is_photo = document is None and _is_photo(replied)
        if document is None and not is_photo:
            await safe_edit_message(message, "❌ 不支持的媒体类型，请回复贴纸或图片")
            return

        await safe_edit_message(message, "正在保存到贴纸包...")
        if document is None and is_photo:
            buffer = await replied.download_media(file=bytes)
            if not buffer:
                await safe_edit_message(message, "❌ 下载图片失败")
                return
            document = await client.upload_file(buffer, file_name="sticker.png")

        sticker_item = tl_types.InputStickerSetItem(document=document, emoji=STICKER_EMOJI)
        stickerset = tl_types.InputStickerSetShortName(short_name=short_name)
        try:
            exists = await self._sticker_set_exists(client, short_name)
            if exists:
                await client(tl_functions.stickers.AddStickerToSetRequest(stickerset=stickerset, sticker=sticker_item))
            else:
                me = await client.get_me()
                await client(tl_functions.stickers.CreateStickerSetRequest(
                    user_id=me,
                    title=short_name,
                    short_name=short_name,
                    stickers=[sticker_item],
                ))
            await safe_edit_message(
                message,
                f"✅ 已保存到贴纸包\nt.me/addstickers/{html.escape(short_name)}",
                parse_mode="html",
            )
        except Exception as exc:
            logger.exception("保存贴纸包失败")
            await safe_edit_message(message, f"❌ 保存失败：{html.escape(str(exc))}", parse_mode="html")

    async def _sticker_set_exists(self, client: Any, short_name: str) -> bool:
        try:
            await client(tl_functions.messages.GetStickerSetRequest(
                stickerset=tl_types.InputStickerSetShortName(short_name=short_name),
                hash=0,
            ))
            return True
        except Exception as exc:
            if "STICKERSET_INVALID" in str(exc):
                return False
            raise

    # ---- 配置 ----

    async def _handle_config(self, event: Any, args: list[str]) -> None:
        message = event_message(event)
        prefix = self._primary_prefix()
        if not args:
            name = self.config.sticker_set_short_name or "(未设置)"
            link = (
                f"\n贴纸包链接: t.me/addstickers/{html.escape(self.config.sticker_set_short_name)}"
                if self.config.sticker_set_short_name
                else ""
            )
            await safe_edit_message(
                message,
                f"<b>📋 当前配置</b>\n贴纸包: <code>{html.escape(name)}</code>{link}\n\n"
                f"设置: <code>{html.escape(prefix)} config sticker 名称</code>",
                parse_mode="html",
            )
            return
        sub = args[0].lower()
        if sub in {"sticker", "stickerset", "set"}:
            new_name = "_".join(args[1:]).strip()
            if not new_name:
                await safe_edit_message(message, "❌ 请提供贴纸包名称")
                return
            if not re.fullmatch(r"[A-Za-z0-9_]+", new_name) or len(new_name) > 64:
                await safe_edit_message(message, "❌ 贴纸包名称只能包含字母、数字和下划线（≤64）")
                return
            self.config.sticker_set_short_name = new_name
            self._sync_card_config()
            await safe_edit_message(
                message,
                f"✅ 贴纸包已设置为 <code>{html.escape(new_name)}</code>\n"
                f"⚠️ 该设置在内存生效，重启保留需在后台配置或写入 config.json",
                parse_mode="html",
            )
        else:
            await safe_edit_message(message, f"❌ 未知配置项 <code>{html.escape(sub)}</code>", parse_mode="html")

    # ---- 杂项 ----

    def _primary_prefix(self) -> str:
        for item in self.config.command_prefixes:
            if item.strip():
                return item.strip()
        return "/q"

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)
        self.card.metrics.update({"telethon": "available" if tl_types is not None else "missing"})

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        root = self.project_root or Path.cwd()
        return root / path


# ---- 命令解析 ----


def parse_quote_command(text: str, prefixes: list[str]) -> dict[str, Any] | None:
    after = _strip_prefix(text, prefixes)
    if after is None:
        return None
    tokens = after.split()
    if not tokens:
        return {"kind": "generate", "count": 1, "with_reply": False}
    head = tokens[0].lower()
    if head == "config":
        return {"kind": "config", "args": tokens[1:]}
    if head == "f":
        return {"kind": "fake", "content": after[len(tokens[0]):].strip()}
    if head == "s":
        return {"kind": "save"}
    if head == "r":
        return {"kind": "generate", "count": _safe_int(tokens[1]) if len(tokens) > 1 else 1, "with_reply": True}
    if head.isdigit():
        return {"kind": "generate", "count": _safe_int(tokens[0]), "with_reply": False}
    return {"kind": "generate", "count": 1, "with_reply": False}


def _strip_prefix(text: str, prefixes: list[str]) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for prefix in sorted((p.strip() for p in prefixes if p.strip()), key=len, reverse=True):
        if lowered == prefix.lower():
            return ""
        if lowered.startswith(prefix.lower()):
            rest = stripped[len(prefix):]
            if not rest or rest[0].isspace() or prefix.startswith("/"):
                return rest.strip()
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 1


# ---- 发送者 / 用户数据 ----


async def _resolve_sender(message: Any, client: Any) -> Any:
    sender = None
    try:
        if hasattr(message, "get_sender"):
            sender = await message.get_sender()
    except Exception:
        sender = None
    if sender is None and client is not None:
        peer = getattr(message, "peer_id", None) or getattr(message, "from_id", None)
        if peer is not None and hasattr(client, "get_entity"):
            try:
                sender = await client.get_entity(peer)
            except Exception:
                logger.warning("从 peer 获取发送者失败", exc_info=True)
    if getattr(message, "fwd_from", None):
        forwarded = None
        forward = getattr(message, "forward", None)
        if forward is not None:
            forwarded = getattr(forward, "sender", None) or getattr(forward, "chat", None)
            if forwarded is None and hasattr(forward, "get_sender"):
                try:
                    forwarded = await forward.get_sender()
                except Exception:
                    forwarded = None
        if forwarded is not None:
            sender = forwarded
    return sender


async def _enrich_sender(sender: Any, client: Any) -> Any:
    """把可能不完整的发送者补全为完整用户实体。

    群里消息的 get_sender() 有时返回缺字段的实体（例如丢了 last_name），
    导致名字里的 emoji（写在姓/名里）被吃掉。用 get_entity 重取以拿到完整名字。
    """
    if sender is None or client is None or not hasattr(client, "get_entity"):
        return sender
    sender_id = getattr(sender, "id", None)
    if not isinstance(sender_id, int):
        return sender
    try:
        full = await client.get_entity(sender_id)
    except Exception:
        logger.debug("补全发送者实体失败，沿用原实体", exc_info=True)
        return sender
    return full or sender


async def _build_quote_user(sender: Any, client: Any, with_avatar: bool) -> dict[str, Any]:
    sender = await _enrich_sender(sender, client)
    user_id = getattr(sender, "id", None)
    first_name = getattr(sender, "first_name", "") or getattr(sender, "title", "") or ""
    last_name = getattr(sender, "last_name", "") or ""
    username = getattr(sender, "username", "") or ""
    name = _sender_display_name(sender)

    # 诊断：打印解析到的发送者真实字段，定位名字里 emoji 丢失的原因（确认后可删）
    logger.info(
        "QUOTE_SENDER_DEBUG type=%s id=%s first_name=%r last_name=%r name=%r username=%r emoji_status=%r",
        type(sender).__name__, user_id, first_name, last_name, name, username,
        getattr(sender, "emoji_status", None),
    )

    photo = None
    if with_avatar and client is not None and hasattr(client, "download_profile_photo"):
        try:
            buffer = await client.download_profile_photo(sender, file=bytes)
            if buffer:
                photo = {"url": "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")}
        except Exception:
            logger.warning("下载头像失败", exc_info=True)

    user = {
        "id": int(user_id) if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()) else _hash_id(name),
        "name": name if with_avatar else "",
        "first_name": (first_name or None) if with_avatar else None,
        "last_name": (last_name or None) if with_avatar else None,
        "username": (username or None) if (photo and with_avatar) else None,
        "photo": photo,
    }
    return {key: value for key, value in user.items() if value is not None}


async def _build_reply_block(message: Any, client: Any) -> dict[str, Any] | None:
    try:
        replied = await get_reply_message(message)
    except Exception:
        replied = None
    if replied is None:
        return None
    selected_quote = _selected_quote_for_message(message, replied)
    text = selected_quote["text"] if selected_quote else message_text(replied)
    if not text:
        return None
    entities = selected_quote["entities"] if selected_quote else (getattr(replied, "entities", []) or [])
    sender = await _resolve_sender(replied, client)
    name = "unknown"
    chat_id = None
    if sender is not None:
        chat_id = getattr(sender, "id", None)
        name = _sender_display_name(sender) or "unknown"
    block: dict[str, Any] = {
        "name": name,
        "text": text,
        "entities": quote_api.convert_entities(entities),
    }
    if isinstance(chat_id, int):
        block["chatId"] = chat_id
    return block


def _selected_quote_for_message(replying_message: Any, target_message: Any) -> dict[str, Any] | None:
    selected = _selected_quote(replying_message)
    if selected is None:
        return None
    replied_id = _reply_to_message_id(replying_message)
    target_id = getattr(target_message, "id", None)
    if replied_id is not None and target_id is not None and str(replied_id) != str(target_id):
        return None
    return selected


def _selected_quote(message: Any) -> dict[str, Any] | None:
    reply_header = getattr(message, "reply_to", None)
    if reply_header is None:
        return None
    quote_text = _string_attr(reply_header, "quote_text")
    quote_entities = getattr(reply_header, "quote_entities", None)
    nested_quote = getattr(reply_header, "quote", None)
    if not quote_text and nested_quote is not None and not isinstance(nested_quote, bool):
        quote_text = _string_attr(nested_quote, "text") or _string_attr(nested_quote, "quote_text")
        quote_entities = getattr(nested_quote, "entities", None) or getattr(nested_quote, "quote_entities", None)
    if not quote_text:
        return None
    return {"text": quote_text.strip(), "entities": quote_entities or []}


def _reply_to_message_id(message: Any) -> Any:
    reply_header = getattr(message, "reply_to", None)
    if reply_header is None:
        return None
    return getattr(reply_header, "reply_to_msg_id", None) or getattr(reply_header, "message_id", None)


def _string_attr(obj: Any, attr: str) -> str:
    value = getattr(obj, attr, "")
    return value if isinstance(value, str) else ""


def _sender_display_name(sender: Any) -> str:
    name = getattr(sender, "name", "") or ""
    if name:
        return str(name)
    first = getattr(sender, "first_name", "") or getattr(sender, "title", "") or ""
    last = getattr(sender, "last_name", "") or ""
    composed = f"{first} {last}".strip()
    return composed or (getattr(sender, "username", "") or "")


def _hash_id(text: str) -> int:
    digest = hashlib.md5((text or "fake_quote_user").encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


# ---- 贴纸包辅助 ----


def _sticker_input_document(message: Any) -> Any:
    if tl_types is None:
        return None
    media = getattr(message, "media", None)
    document = getattr(media, "document", None)
    if document is None:
        return None
    attributes = getattr(document, "attributes", []) or []
    is_sticker = any(attr.__class__.__name__ == "DocumentAttributeSticker" for attr in attributes)
    if not is_sticker:
        return None
    doc_id = getattr(document, "id", None)
    access_hash = getattr(document, "access_hash", None)
    if doc_id is None or access_hash is None:
        return None
    return tl_types.InputDocument(
        id=doc_id,
        access_hash=access_hash,
        file_reference=getattr(document, "file_reference", b"") or b"",
    )


def _is_photo(message: Any) -> bool:
    media = getattr(message, "media", None)
    return media is not None and media.__class__.__name__ == "MessageMediaPhoto"


# ---- 媒体嵌入 ----

MAX_QUOTE_MEDIA_BYTES = 25 * 1024 * 1024


async def _build_media(message: Any) -> dict[str, Any] | None:
    if getattr(message, "media", None) is None:
        return None
    try:
        mime = telegram_media.media_mime_type(message)
        is_sticker = telegram_media.media_has_sticker_attribute(message)
        is_tgs = telegram_media.media_is_tgs_sticker(message)
        is_motion = telegram_media.media_is_motion(message)
        buffer = await message.download_media(file=bytes)
        if not buffer or len(buffer) > MAX_QUOTE_MEDIA_BYTES:
            return None
        final_buffer = buffer
        final_mime = mime
        if is_tgs or quote_api.is_gzip_tgs(buffer):
            converted = await asyncio.to_thread(_convert_tgs_to_webm, buffer)
            if not converted:
                return None
            final_buffer, final_mime = converted, "video/webm"
        elif is_motion or quote_api.is_mp4(buffer):
            converted = await asyncio.to_thread(_convert_to_webm, buffer, telegram_media.media_file_suffix(message))
            if converted:
                final_buffer, final_mime = converted, "video/webm"
        mime = final_mime or ("image/webp" if is_sticker else "image/jpeg")
        return {"url": f"data:{mime};base64," + base64.b64encode(final_buffer).decode("ascii")}
    except Exception:
        logger.warning("处理语录媒体失败", exc_info=True)
        return None


def _convert_to_webm(buffer: bytes, suffix: str) -> bytes | None:
    if not shutil.which("ffmpeg"):
        return None
    suffix = suffix if suffix.startswith(".") and len(suffix) <= 8 else ".bin"
    with tempfile.TemporaryDirectory(prefix="tg_quote_") as tmp:
        in_path = Path(tmp) / f"in{suffix}"
        out_path = Path(tmp) / "out.webm"
        in_path.write_bytes(buffer)
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(in_path), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                 "-b:v", "400k", "-auto-alt-ref", "0", "-an", "-y", str(out_path)],
                check=True, capture_output=True, timeout=60,
            )
            if out_path.exists() and out_path.stat().st_size:
                return out_path.read_bytes()
        except Exception:
            logger.warning("转 WebM 失败", exc_info=True)
    return None


def _convert_tgs_to_webm(buffer: bytes) -> bytes | None:
    try:
        from rlottie_python import LottieAnimation
    except ImportError:
        logger.info("缺少 rlottie-python，跳过 TGS 语录媒体")
        return None
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory(prefix="tg_quote_tgs_") as tmp:
        tgs_path = Path(tmp) / "in.tgs"
        gif_path = Path(tmp) / "mid.gif"
        out_path = Path(tmp) / "out.webm"
        tgs_path.write_bytes(buffer)
        try:
            LottieAnimation.from_tgs(str(tgs_path)).save_animation(str(gif_path))
            subprocess.run(
                ["ffmpeg", "-i", str(gif_path), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                 "-b:v", "400k", "-auto-alt-ref", "0", "-an", "-y", str(out_path)],
                check=True, capture_output=True, timeout=60,
            )
            if out_path.exists() and out_path.stat().st_size:
                return out_path.read_bytes()
        except Exception:
            logger.warning("TGS 转 WebM 失败", exc_info=True)
    return None
