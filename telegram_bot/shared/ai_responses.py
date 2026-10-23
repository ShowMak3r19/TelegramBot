"""OpenAI Responses 兼容接口的共享适配层。

集中图像输入构造与响应解析逻辑，供 ai_reply / ai_decrypt / ai_image 等模块复用，
避免功能模块之间互相 import。
"""

from __future__ import annotations

import base64
import html
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from telegram_bot.shared.telegram_io import (
    event_message as _event_message,
    get_reply_message as _get_reply_message,
    obj_get,
    unlink_quietly as _unlink_quietly,
)
from telegram_bot.shared.telegram_media import (
    extract_motion_media_frames_as_jpegs,
    media_bytes_to_responses_image_url,
    media_is_motion,
    media_is_tgs_sticker,
    media_size_bytes,
)

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - exercised only in deployments missing deps.
    AsyncOpenAI = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MAX_IMAGE_INPUTS = 10
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_MOTION_MEDIA_BYTES = 512 * 1024 * 1024
MAX_MOTION_FRAMES = 6
MAX_SOURCE_LINKS = 8


async def collect_image_inputs_for_responses(
    event_or_message: Any,
    prompt: str = "",
    *,
    include_reply_media: bool = True,
) -> tuple[list[dict[str, str]], str | None]:
    event = event_or_message if hasattr(event_or_message, "message") else None
    message = _event_message(event_or_message)
    explicit_indexes = extract_requested_image_indexes(prompt)
    targets: list[tuple[str, Any]] = []
    if getattr(message, "media", None):
        targets.append(("当前消息图片", message))
    if include_reply_media and getattr(message, "is_reply", False):
        replied = await _get_reply_message(message)
        if replied is not None and getattr(replied, "media", None):
            reply_targets = await collect_related_media_messages(event, message, replied)
            indexed_reply_targets = list(enumerate(reply_targets, start=1))
            if explicit_indexes:
                indexed_reply_targets = [(index, item) for index, item in indexed_reply_targets if index in explicit_indexes]
            targets.extend((f"引用图{index}", item) for index, item in indexed_reply_targets)

    image_inputs: list[dict[str, str]] = []
    media_errors: list[str] = []
    for label, target in targets[:MAX_IMAGE_INPUTS]:
        remaining_slots = MAX_IMAGE_INPUTS - len(image_inputs)
        if remaining_slots <= 0:
            break
        known_size = media_size_bytes(target)
        if media_is_tgs_sticker(target):
            media_errors.append(f"{label}:TGS_STICKER_UNSUPPORTED")
            logger.info("Skipped unsupported Telegram TGS sticker input label=%s", label)
            continue
        if media_is_motion(target):
            if known_size and known_size > MAX_MOTION_MEDIA_BYTES:
                media_errors.append(f"{label}:TOO_LARGE")
                logger.info("Skipped oversized AI motion media input label=%s bytes=%s", label, known_size)
                continue
            frame_inputs, error = await collect_motion_media_frame_inputs(target, label, min(MAX_MOTION_FRAMES, remaining_slots))
            if error:
                media_errors.append(f"{label}:{error}")
                logger.info("Skipped unsupported AI motion media input label=%s error=%s", label, error)
                continue
            image_inputs.extend(frame_inputs)
            continue

        if known_size and known_size > MAX_MEDIA_BYTES:
            media_errors.append(f"{label}:TOO_LARGE")
            logger.info("Skipped oversized AI media input label=%s bytes=%s", label, known_size)
            continue
        try:
            media = await target.download_media(file=bytes)
        except Exception as exc:
            return image_inputs, f"DOWNLOAD_FAILED:{exc}"
        if not media:
            continue
        if len(media) > MAX_MEDIA_BYTES:
            return image_inputs, "TOO_LARGE"
        image_url, error = media_bytes_to_responses_image_url(media, target)
        if error:
            media_errors.append(f"{label}:{error}")
            logger.info("Skipped unsupported AI media input label=%s error=%s", label, error)
            continue
        image_inputs.append({"label": label, "url": image_url})
    return image_inputs, ";".join(media_errors) if media_errors and not image_inputs else None


async def collect_motion_media_frame_inputs(target: Any, label: str, max_frames: int) -> tuple[list[dict[str, str]], str | None]:
    if max_frames <= 0:
        return [], None
    if not shutil.which("ffmpeg"):
        return [], "FFMPEG_MISSING"
    downloaded_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="tg_ai_motion_") as tmp:
            tmp_path = Path(tmp)
            downloaded = await target.download_media(file=str(tmp_path))
            if not downloaded:
                return [], "DOWNLOAD_EMPTY"
            downloaded_path = Path(downloaded)
            frames = extract_motion_media_frames_as_jpegs(downloaded_path, max_frames)
            if not frames:
                return [], "NO_FRAMES"
            return [
                {
                    "label": f"{label} 关键帧{index}",
                    "url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("utf-8"),
                }
                for index, frame in enumerate(frames, start=1)
            ], None
    except Exception as exc:
        logger.exception("Failed to collect AI motion media frames")
        return [], f"FRAME_EXTRACT_FAILED:{exc}"
    finally:
        _unlink_quietly(downloaded_path)


async def collect_related_media_messages(event: Any, trigger_message: Any, replied: Any) -> list[Any]:
    grouped_id = getattr(replied, "grouped_id", None)
    if not grouped_id:
        return [replied]

    client = getattr(event, "client", None) if event is not None else getattr(trigger_message, "client", None)
    chat_id = getattr(trigger_message, "chat_id", getattr(event, "chat_id", None) if event is not None else None)
    reply_id = int(getattr(replied, "id", 0) or 0)
    if client is None or chat_id is None or reply_id <= 0 or not hasattr(client, "iter_messages"):
        return [replied]

    items: list[Any] = []

    async def collect_with(**kwargs: Any) -> None:
        async for item in client.iter_messages(chat_id, limit=120, **kwargs):
            if getattr(item, "grouped_id", None) == grouped_id and getattr(item, "media", None):
                items.append(item)

    try:
        await collect_with(max_id=reply_id + 80)
        await collect_with(min_id=max(reply_id - 80, 0))
    except TypeError:
        try:
            await collect_with(max_id=reply_id + 80)
        except Exception:
            logger.exception("Failed to collect replied album media")
            return [replied]
    except Exception:
        logger.exception("Failed to collect replied album media")
        return [replied]

    if not items:
        return [replied]
    unique: dict[int, Any] = {}
    for item in items + [replied]:
        item_id = int(getattr(item, "id", 0) or 0)
        unique[item_id] = item
    return [unique[key] for key in sorted(unique)]


def extract_requested_image_indexes(text: str) -> set[int]:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return set()

    indexes: set[int] = set()
    patterns = [
        rf"图(?P<num>{_image_index_number_pattern()})",
        rf"第(?P<num>{_image_index_number_pattern()})(?:张|幅|个)?图?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, compact, flags=re.IGNORECASE):
            value = parse_image_index_number(match.group("num"))
            if value is not None and value > 0:
                indexes.add(value)
    return indexes


def parse_image_index_number(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        pass
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return mapping.get(value)


def _image_index_number_pattern() -> str:
    return r"\d+|[一二两三四五六七八九十]"


def collect_response_text_and_sources(response: Any) -> tuple[str, list[tuple[str, str]]]:
    all_text_parts: list[str] = []
    final_text_parts: list[str] = []
    sources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for item in obj_get(response, "output", []) or []:
        item_type = obj_get(item, "type")
        if item_type == "web_search_call":
            action = obj_get(item, "action", {}) or {}
            for src in obj_get(action, "sources", []) or []:
                url = obj_get(src, "url")
                if not url or url in seen_urls:
                    continue
                title = obj_get(src, "title") or obj_get(src, "name") or url
                seen_urls.add(url)
                sources.append((str(title), str(url)))
            continue
        if item_type != "message" or obj_get(item, "role") != "assistant":
            continue
        phase = obj_get(item, "phase")
        msg_text_parts: list[str] = []
        msg_refusals: list[str] = []
        for part in obj_get(item, "content", []) or []:
            part_type = obj_get(part, "type")
            if part_type == "output_text":
                txt = obj_get(part, "text")
                if txt:
                    msg_text_parts.append(str(txt))
                for title, url in extract_annotation_sources(obj_get(part, "annotations", []) or []):
                    if url not in seen_urls:
                        seen_urls.add(url)
                        sources.append((title, url))
            elif part_type == "refusal":
                refusal = obj_get(part, "refusal")
                if refusal:
                    msg_refusals.append(str(refusal))
        message_text = "\n".join(msg_text_parts).strip() or "\n".join(msg_refusals).strip()
        if message_text:
            all_text_parts.append(message_text)
            if phase == "final_answer":
                final_text_parts.append(message_text)
    answer = "\n".join(final_text_parts).strip() if final_text_parts else "\n".join(all_text_parts).strip()
    if not answer:
        answer = str(obj_get(response, "output_text", "") or "").strip()
    return answer, sources


def extract_annotation_sources(annotations: Any) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    for annotation in annotations or []:
        url = obj_get(annotation, "url") or obj_get(annotation, "uri")
        if not url:
            file_citation = obj_get(annotation, "file_citation", {}) or {}
            url = obj_get(file_citation, "url")
        if not url or url in seen:
            continue
        title = obj_get(annotation, "title") or obj_get(annotation, "text") or url
        seen.add(str(url))
        sources.append((str(title), str(url)))
    return sources


def collect_reasoning_summary(response: Any) -> str:
    parts: list[str] = []
    for item in obj_get(response, "output", []) or []:
        if obj_get(item, "type") != "reasoning":
            continue
        for part in obj_get(item, "summary", []) or []:
            if obj_get(part, "type") == "summary_text":
                txt = obj_get(part, "text")
                if txt:
                    parts.append(str(txt).strip())
    return "\n\n".join([part for part in parts if part]).strip()


def build_sources_html(sources: list[tuple[str, str]]) -> str:
    if not sources:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for title, url in sources:
        if not url or url in seen:
            continue
        seen.add(url)
        lines.append(f"• <a href='{html.escape(url, quote=True)}'>{html.escape(title or url)}</a>")
        if len(lines) >= MAX_SOURCE_LINKS:
            break
    return "📎 <b>参考来源：</b>\n" + "\n".join(lines) if lines else ""


def build_token_stats(response: Any) -> str:
    counts = extract_usage_counts(response)
    if not counts["total_tokens"]:
        return ""
    return f"Tokens | In: {counts['input_tokens']} | Out: {counts['output_tokens']} | Total: {counts['total_tokens']}"


def extract_usage_counts(source: Any) -> dict[str, int]:
    usage = obj_get(source, "usage", None)
    if usage is None and isinstance(source, dict):
        token_keys = {"input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens"}
        if any(key in source for key in token_keys):
            usage = source
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0}
    input_tokens = _as_nonnegative_int(obj_get(usage, "input_tokens", obj_get(usage, "prompt_tokens", 0)))
    output_tokens = _as_nonnegative_int(obj_get(usage, "output_tokens", obj_get(usage, "completion_tokens", 0)))
    total_tokens = _as_nonnegative_int(obj_get(usage, "total_tokens", 0)) or input_tokens + output_tokens
    input_details = obj_get(usage, "input_tokens_details", obj_get(usage, "prompt_tokens_details", {})) or {}
    output_details = obj_get(usage, "output_tokens_details", obj_get(usage, "completion_tokens_details", {})) or {}
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": _as_nonnegative_int(obj_get(input_details, "cached_tokens", 0)),
        "reasoning_tokens": _as_nonnegative_int(obj_get(output_details, "reasoning_tokens", 0)),
    }


def _as_nonnegative_int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0
