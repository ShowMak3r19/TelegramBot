from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import GifConfig
from telegram_bot.shared.telegram_io import safe_delete_message, safe_edit_message
from telegram_bot.shared import telegram_media
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)

END_MARKERS = {"最后", "最后一秒", "结尾", "末尾", "结束"}
HEAD_MARKERS = {"开头", "头", "头部", "开始", "一开始", "最开始", "从头", "从头开始"}


class GifModule:
    def __init__(self, card: ModuleCard, config: GifConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.output_dir = self._resolve_path(self.config.output_dir)
        self.tmp_dir = self._resolve_path("runtime/tmp")
        self._sync_card_config()

    async def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        message = _event_message(event)
        prompt = extract_gif_prompt(_message_text(message), self.config)
        if prompt is None:
            return HandlerResult.ignored(self.card.id)

        try:
            await self._handle_video_gif(event, prompt)
        except Exception as exc:
            logger.exception("GIF conversion failed: %s", exc)
            return HandlerResult.failed(self.card.id, str(exc))
        return HandlerResult.handled(self.card.id, "gif generated", {"prompt": prompt})

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("gif", values)
        if not isinstance(data, dict):
            return
        self.config = gif_config_from_dict({**asdict(self.config), **data})
        self.output_dir = self._resolve_path(self.config.output_dir)
        self._sync_card_config()

    async def _handle_video_gif(self, event: Any, prompt: str) -> None:
        message = _event_message(event)
        if not getattr(message, "is_reply", False):
            await safe_edit_message(message, format_gif_status_message("", "请回复一个视频/GIF/WebP 后再使用动图命令。", self.config), parse_mode="html")
            return

        replied = await _get_reply_message(message)
        if not replied or not getattr(replied, "media", None) or not media_can_convert(replied):
            await safe_edit_message(message, format_gif_status_message(prompt, "引用消息不是可转换的视频/GIF/WebP。", self.config), parse_mode="html")
            return

        display_prompt = prompt or "引用视频转动图"
        await safe_edit_message(message, format_gif_status_message(display_prompt, "已触发，正在下载引用媒体……", self.config), parse_mode="html")

        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", "chat"))
        message_id = getattr(message, "id", "message")
        output_path = self.output_dir / f"tg_gif_{chat_id}_{message_id}.gif"
        downloaded_path: Path | None = None
        try:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            downloaded = await replied.download_media(file=self.tmp_dir)
            if not downloaded:
                await safe_edit_message(message, format_gif_status_message(display_prompt, "引用媒体下载失败。", self.config), parse_mode="html")
                return
            downloaded_path = Path(downloaded)
            start_seconds, end_seconds = parse_gif_time_range(prompt) or (0.0, None)
            if start_seconds or end_seconds is not None:
                await safe_edit_message(
                    message,
                    format_gif_status_message(display_prompt, f"正在按时间段转换：{format_time_range(start_seconds, end_seconds)}……", self.config),
                    parse_mode="html",
                )
            else:
                await safe_edit_message(message, format_gif_status_message(display_prompt, "正在直接转换为 GIF……", self.config), parse_mode="html")

            gif_path = await asyncio.to_thread(convert_media_to_gif, downloaded_path, output_path, self.config, start_seconds, end_seconds)
            await safe_edit_message(message, format_gif_status_message(display_prompt, "GIF 已生成，正在发送……", self.config), parse_mode="html")
            await event.client.send_file(
                getattr(message, "chat_id", getattr(event, "chat_id", None)),
                file=str(gif_path),
                caption=format_gif_caption(display_prompt, self.config),
                parse_mode="html",
                force_document=False,
                reply_to=getattr(replied, "id", None),
            )
            await safe_delete_message(message, "gif_cleanup")
        except Exception as exc:
            logger.exception("Video to GIF failed: %s", exc)
            await safe_edit_message(message, format_gif_status_message(display_prompt, f"GIF 转换失败：{exc}", self.config), parse_mode="html")
        finally:
            _unlink_quietly(downloaded_path)

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)
        self.card.metrics.update(
            {
                "ffmpeg": "available" if ffmpeg_available() else "missing",
                "output_dir": str(self.output_dir),
            }
        )

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        root = self.project_root or Path.cwd()
        return root / path


def extract_gif_prompt(text: str, config: GifConfig) -> str | None:
    return extract_command_prompt(text, config.command_prefixes)


def extract_command_prompt(text: str, prefixes: list[str]) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for prefix in prefixes:
        prefix = prefix.strip()
        if not prefix:
            continue
        if lowered == prefix.lower():
            return ""
        if lowered.startswith(prefix.lower()):
            rest = stripped[len(prefix) :]
            if not rest or rest[0].isspace() or prefix.startswith("/"):
                return rest.strip()
    return None


def parse_gif_time_range(text: str) -> tuple[float, float | None] | None:
    compact = _normalize_time_text(text)
    if not compact:
        return None

    for delimiter in ("截止到", "一直到", "到", "至", "-", "~", "—", "－"):
        if delimiter not in compact:
            continue
        left, right = compact.split(delimiter, 1)
        start = parse_time_token(left, allow_bare=True)
        end = parse_time_token(right, allow_bare=True)
        if start in {None, "invalid"} or end == "invalid":
            continue
        if end is not None and end <= start:
            return None
        return max(0.0, float(start)), end

    start_match = re.search(r"(?:从|由|自)?(?P<start>.+?)(?:开始|起)(?:到(?:最后|结尾|末尾|结束))?$", compact)
    if start_match:
        start = parse_time_token(start_match.group("start"), allow_bare=False)
        if isinstance(start, (int, float)):
            return max(0.0, float(start)), None
    return None


def parse_time_token(value: str, allow_bare: bool = False) -> float | None | str:
    token = _strip_time_token(value)
    if not token:
        return "invalid"
    if token in HEAD_MARKERS:
        return 0.0
    if token in END_MARKERS:
        return None

    colon_match = re.fullmatch(r"(?:(\d+(?:\.\d+)?):)?(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", token)
    if colon_match:
        first, second, third = colon_match.groups()
        if first is None:
            return float(second) * 60 + float(third)
        return float(first) * 3600 + float(second) * 60 + float(third)

    total = 0.0
    matched = False
    hour_match = re.search(rf"({_number_pattern()})(?:小时|钟头)", token)
    if hour_match:
        value = parse_chinese_number(hour_match.group(1))
        if value is None:
            return "invalid"
        total += value * 3600
        matched = True
    minute_match = re.search(rf"({_number_pattern()})(?:分钟|分)", token)
    if minute_match:
        value = parse_chinese_number(minute_match.group(1))
        if value is None:
            return "invalid"
        total += value * 60
        matched = True
    second_match = re.search(rf"({_number_pattern()})(?:秒钟|秒|s|S)", token)
    if second_match:
        value = parse_chinese_number(second_match.group(1))
        if value is None:
            return "invalid"
        total += value
        matched = True
    if matched:
        return total

    if allow_bare and re.fullmatch(_number_pattern(), token):
        number = parse_chinese_number(token)
        return "invalid" if number is None else number
    return "invalid"


def parse_chinese_number(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass

    digit_values = {
        "零": 0,
        "〇": 0,
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
    }
    if value in digit_values:
        return float(digit_values[value])
    total = 0
    section = 0
    number = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for char in value:
        if char in digit_values:
            number = digit_values[char]
        elif char in units:
            section += (number or 1) * units[char]
            number = 0
        else:
            return None
    return float(total + section + number)


def format_time_range(start_seconds: float, end_seconds: float | None) -> str:
    if end_seconds is None:
        return f"从 {start_seconds:g}s 到结尾"
    return f"从 {start_seconds:g}s 到 {end_seconds:g}s"


def format_gif_status_message(prompt: str, status: str, config: GifConfig) -> str:
    safe_prompt = html.escape(prompt.strip() or "引用视频转动图")
    safe_status = html.escape(status.strip())
    return (
        "🎞 <b>GIF 动图</b>\n"
        f"<blockquote expandable>{safe_prompt}</blockquote>\n\n"
        f"⏳ <b>Status</b>: {safe_status}\n\n"
        f"🎚 <b>FPS</b>: <code>{int(config.fps)}</code> | "
        f"📐 <b>Width</b>: <code>{html.escape(str(config.width))}</code> | "
        f"⏱ <b>Max</b>: <code>{float(config.max_seconds):g}s</code> | "
        f"📦 <b>Target</b>: <code>{int(config.max_bytes) / 1024 / 1024:.1f}MB</code>"
    )


def format_gif_caption(prompt: str, config: GifConfig) -> str:
    safe_prompt = html.escape(prompt.strip() or "引用视频转动图")
    return (
        "🎞 <b>GIF 动图</b>\n"
        f"<blockquote expandable>{safe_prompt}</blockquote>\n"
        f"🎚 <b>FPS</b>: <code>{int(config.fps)}</code> | "
        f"📐 <b>Width</b>: <code>{html.escape(str(config.width))}</code>"
    )


def convert_media_to_gif(media_path: Path, output_path: Path, config: GifConfig, start_seconds: float = 0.0, end_seconds: float | None = None) -> Path:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 未安装，无法转换视频/动图。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start_seconds = max(0.0, float(start_seconds or 0.0))
    if end_seconds is not None and end_seconds <= start_seconds:
        raise ValueError("结束时间必须大于开始时间。")

    media_duration = probe_media_duration_seconds(media_path)
    source_width, _ = probe_media_dimensions(media_path)
    if media_duration and start_seconds >= media_duration:
        raise ValueError(f"开始时间 {start_seconds:g}s 已超过视频长度 {media_duration:.1f}s。")
    if end_seconds is not None:
        duration_seconds = end_seconds - start_seconds
    elif media_duration and media_duration > start_seconds:
        duration_seconds = media_duration - start_seconds
    else:
        duration_seconds = config.max_seconds
    duration_seconds = max(0.1, min(float(duration_seconds), float(config.max_seconds)))

    gif_width = normalize_gif_width(config.width)
    if gif_width == "auto":
        base_width = min(source_width, 480) if source_width else 480
    else:
        base_width = min(int(gif_width), source_width) if source_width else int(gif_width)
    base_width = max(128, min(base_width, 1600))

    last_size = 0
    for attempt, (attempt_fps, attempt_width) in enumerate(_conversion_candidates(config.fps, base_width), start=1):
        vf = (
            f"fps={attempt_fps},"
            f"scale='min({attempt_width},iw)':-2:flags=lanczos,"
            "split[s0][s1];[s0]palettegen=stats_mode=diff:max_colors=128[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=5"
        )
        command = ["ffmpeg", "-y"]
        if start_seconds > 0:
            command.extend(["-ss", f"{start_seconds:.3f}"])
        command.extend(["-t", f"{duration_seconds:.3f}", "-i", str(media_path), "-vf", vf, str(output_path)])
        subprocess.run(command, check=True, capture_output=True, timeout=max(30, int(duration_seconds) + 30))
        last_size = output_path.stat().st_size
        logger.info(
            "GIF conversion attempt=%s fps=%s width=%s bytes=%s target_bytes=%s",
            attempt,
            attempt_fps,
            attempt_width,
            last_size,
            config.max_bytes or "disabled",
        )
        if not config.max_bytes or last_size <= config.max_bytes:
            break
    logger.info("GIF converted path=%s start=%.3f duration=%.3f bytes=%s", output_path, start_seconds, duration_seconds, last_size)
    return output_path


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def probe_media_duration_seconds(media_path: Path) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        return max(0.0, float(result.stdout.strip() or "0"))
    except Exception:
        return 0.0


def probe_media_dimensions(media_path: Path) -> tuple[int, int]:
    if not shutil.which("ffprobe"):
        return 0, 0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(media_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        width, height = (result.stdout.strip() or "0x0").split("x", 1)
        return int(width or 0), int(height or 0)
    except Exception:
        return 0, 0


def media_can_convert(message: Any) -> bool:
    return telegram_media.media_can_convert_to_gif(message)


def normalize_gif_width(value: Any) -> int | str:
    if str(value).strip().lower() == "auto":
        return "auto"
    try:
        return max(128, min(int(value), 1600))
    except (TypeError, ValueError):
        return "auto"


def gif_config_from_dict(data: dict[str, Any]) -> GifConfig:
    return GifConfig(
        command_prefixes=_clean_list(data.get("command_prefixes")) or ["/vgif", "动图", "视频动图", "转动图"],
        output_dir=str(data.get("output_dir") or "runtime/data/generated_gifs"),
        max_seconds=max(1.0, min(float(data.get("max_seconds") or 8.0), 120.0)),
        fps=max(1, min(int(data.get("fps") or 12), 30)),
        width=str(normalize_gif_width(data.get("width", "auto"))),
        max_bytes=max(0, min(int(data.get("max_bytes") or 0), 80 * 1024 * 1024)),
    )


def _conversion_candidates(fps: int, width: int) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for fps_value, width_value in [
        (fps, width),
        (min(fps, 12), min(width, 480)),
        (min(fps, 10), min(width, 360)),
        (min(fps, 8), min(width, 320)),
        (min(fps, 6), min(width, 240)),
    ]:
        candidate = (max(4, int(fps_value)), max(160, int(width_value)))
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _number_pattern() -> str:
    return r"\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千]+"


def _normalize_time_text(text: str) -> str:
    return (
        re.sub(r"\s+", "", text.strip())
        .replace("：", ":")
        .replace("～", "~")
        .replace("——", "-")
        .replace("–", "-")
    )


def _strip_time_token(value: str) -> str:
    token = value.strip().strip("，,。.!！?？:：")
    token = re.sub(r"^(从|由|自)", "", token)
    if token in HEAD_MARKERS or token in END_MARKERS:
        return token
    token = token.removeprefix("第")
    token = re.sub(r"(开始|起)$", "", token)
    token = token.removeprefix("第")
    return token


def _event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def _message_text(message: Any) -> str:
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, "")
        if isinstance(value, str):
            return value.strip()
    return ""


def _is_outgoing(event: Any) -> bool:
    message = _event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


async def _get_reply_message(message: Any) -> Any:
    if message is None or not getattr(message, "is_reply", False) or not hasattr(message, "get_reply_message"):
        return None
    try:
        return await message.get_reply_message()
    except Exception:
        logger.exception("Failed to load GIF replied message")
        return None


def _media_mime_type(message: Any) -> str:
    return telegram_media.media_mime_type(message)


def _media_file_name(message: Any) -> str:
    return telegram_media.media_file_name(message)


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
