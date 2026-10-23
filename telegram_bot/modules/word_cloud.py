from __future__ import annotations

import asyncio
import html
import logging
import math
import re
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import WordCloudConfig
from telegram_bot.shared.telegram_io import safe_delete_message, safe_edit_message
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - Pillow is declared in requirements.
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


DEFAULT_STOP_WORDS = {
    "这个", "那个", "就是", "不是", "可以", "没有", "一下", "一个", "什么", "怎么", "为什么",
    "然后", "现在", "还是", "但是", "因为", "所以", "如果", "已经", "应该", "可能", "感觉",
    "不要", "知道", "看看", "哈哈", "哈哈哈", "你们", "我们", "他们", "自己", "直接", "确实",
    "来源", "情况", "情况下", "耗时", "输入", "输出", "回复", "问题", "最近", "消息", "有效",
    "今天", "昨天", "明天", "时候", "东西", "里面", "这里", "那里", "这样", "那样", "进行",
    "使用", "需要", "更新", "主要", "内容", "新增", "版本", "发布", "包括", "所有", "不会",
    "the", "and", "for", "with", "this", "that", "you", "are", "not", "but", "from", "have",
    "http", "https", "com", "www", "telegram", "t.me", "true", "false", "null", "undefined",
}
PALETTE = ["#0f766e", "#166534", "#1d4ed8", "#0891b2", "#2563eb", "#ca8a04", "#dc2626", "#7c3aed"]
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
ASCII_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+\-.]{1,24}")
NUMBER_RE = re.compile(r"\d{2,}[a-zA-Z%]?")
MENTION_TAG_RE = re.compile(r"[@#][\w_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff-]+")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class WordCloudModule:
    def __init__(self, card: ModuleCard, config: WordCloudConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.output_dir = self._resolve_path(self.config.output_dir)
        self._sync_card_config()

    async def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        message = _event_message(event)
        prompt = extract_word_cloud_prompt(_message_text(message), self.config)
        if prompt is None:
            return HandlerResult.ignored(self.card.id)

        try:
            await self._handle_word_cloud(event, prompt)
        except Exception as exc:
            logger.exception("Word cloud generation failed: %s", exc)
            return HandlerResult.failed(self.card.id, str(exc))
        return HandlerResult.handled(self.card.id, "word cloud sent", {"prompt": prompt})

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("word_cloud", values)
        if not isinstance(data, dict):
            return
        self.config = word_cloud_config_from_dict({**asdict(self.config), **data})
        self.output_dir = self._resolve_path(self.config.output_dir)
        self._sync_card_config()

    async def _handle_word_cloud(self, event: Any, prompt: str) -> None:
        message = _event_message(event)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        client = getattr(event, "client", None)
        if client is None or chat_id is None or not hasattr(client, "iter_messages"):
            await safe_edit_message(message, format_word_cloud_status("无法读取当前聊天消息。"), parse_mode="html")
            return

        limit = parse_word_cloud_limit(prompt, self.config)
        status_message = message
        if self.config.delete_command:
            deleted = await safe_delete_message(message, "word_cloud_command")
            if deleted and hasattr(client, "send_message"):
                status_message = await client.send_message(
                    chat_id,
                    format_word_cloud_status(f"正在统计最近 {limit} 条消息……"),
                    parse_mode="html",
                )
            else:
                await safe_edit_message(message, format_word_cloud_status(f"正在统计最近 {limit} 条消息……"), parse_mode="html")
        else:
            await safe_edit_message(message, format_word_cloud_status(f"正在统计最近 {limit} 条消息……"), parse_mode="html")

        try:
            messages = await fetch_recent_messages(client, chat_id, limit)
            words, valid_messages = build_word_cloud_from_messages(messages, self.config)
            if not words:
                await safe_edit_message(status_message, format_word_cloud_status("没有统计到足够的热词。"), parse_mode="html")
                return
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / f"word_cloud_{_safe_chat_id(chat_id)}_{int(time.time() * 1000)}.png"
            await asyncio.to_thread(render_word_cloud_png, words, limit, valid_messages, self.config, output_path)
            if not hasattr(client, "send_file"):
                await safe_edit_message(status_message, format_word_cloud_status("Telegram 客户端不支持发送图片。"), parse_mode="html")
                return
            await client.send_file(
                chat_id,
                file=str(output_path),
                caption="",
                force_document=False,
                reply_to=getattr(message, "id", None) if not self.config.delete_command else None,
            )
            if status_message is not message or self.config.delete_command:
                await safe_delete_message(status_message, "word_cloud_status_cleanup")
            logger.info(
                "Word cloud sent: chat_id=%s limit=%s valid_messages=%s words=%s",
                chat_id,
                limit,
                valid_messages,
                len(words),
            )
        except Exception as exc:
            logger.exception("Word cloud command failed: %s", exc)
            await safe_edit_message(status_message, format_word_cloud_status(f"词云生成失败：{exc}"), parse_mode="html")

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)
        self.card.metrics.update(
            {
                "output_dir": str(self.output_dir),
                "pillow": "available" if Image is not None else "missing",
            }
        )

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        root = self.project_root or Path.cwd()
        return root / path


async def fetch_recent_messages(client: Any, chat_id: Any, limit: int) -> list[Any]:
    messages: list[Any] = []
    async for item in client.iter_messages(chat_id, limit=limit):
        messages.append(item)
    return messages


def build_word_cloud_from_messages(messages: list[Any], config: WordCloudConfig) -> tuple[list[dict[str, Any]], int]:
    counts: Counter[str] = Counter()
    valid_messages = 0
    for item in messages:
        text = _message_text(item).strip()
        if not text or should_ignore_message_text(text, config):
            continue
        valid_messages += 1
        collect_words(text, counts, config)
    return build_word_items(counts), valid_messages


def should_ignore_message_text(text: str, config: WordCloudConfig) -> bool:
    stripped = text.strip()
    if extract_word_cloud_prompt(stripped, config) is not None:
        return True
    return any(stripped.startswith(prefix) for prefix in config.ignore_command_prefixes if prefix)


def collect_words(text: str, counts: Counter[str], config: WordCloudConfig) -> None:
    cleaned = URL_RE.sub(" ", text)
    cleaned = MENTION_TAG_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[^\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaffa-zA-Z0-9_+\-.]+", " ", cleaned)

    for match in ASCII_WORD_RE.finditer(cleaned):
        add_word(counts, match.group(0), config, 2)
    for match in NUMBER_RE.finditer(cleaned):
        add_word(counts, match.group(0), config, 1)
    for match in HAN_RE.finditer(cleaned):
        part = match.group(0)
        if len(part) <= 4:
            add_word(counts, part, config, 3)
            continue
        for size in range(2, 6):
            for index in range(0, len(part) - size + 1):
                word = part[index : index + size]
                edge_bonus = 1 if index == 0 or index == len(part) - size else 0
                add_word(counts, word, config, (1 + edge_bonus) if size <= 3 else (2 + edge_bonus))


def add_word(counts: Counter[str], word: str, config: WordCloudConfig, weight: int = 1) -> None:
    normalized = word.strip().lower()
    if not is_useful_word(normalized, config):
        return
    counts[normalized] += weight


def is_useful_word(word: str, config: WordCloudConfig) -> bool:
    if not word:
        return False
    stop_words = DEFAULT_STOP_WORDS | {item.strip().lower() for item in config.stop_words if item.strip()}
    if word in stop_words:
        return False
    if word.isdigit():
        return False
    if re.fullmatch(r"[a-z]{1,2}", word, re.IGNORECASE):
        return False
    if re.fullmatch(r"[o0]+", word, re.IGNORECASE):
        return False
    if re.fullmatch(r"[._+\-]+", word):
        return False
    return True


def build_word_items(counts: Counter[str]) -> list[dict[str, Any]]:
    entries = [(word, count) for word, count in counts.most_common() if count >= 2][:220]
    if not entries:
        return []
    max_count = entries[0][1]
    min_count = entries[-1][1]
    spread = max(1, max_count - min_count)
    items: list[dict[str, Any]] = []
    for index, (word, count) in enumerate(entries):
        ratio = (count - min_count) / spread
        size = round(12 + math.pow(ratio, 0.7) * 68)
        items.append({"word": word, "count": count, "size": size, "color": PALETTE[index % len(PALETTE)]})
    return items


def render_word_cloud_png(words: list[dict[str, Any]], limit: int, valid_messages: int, config: WordCloudConfig, output_path: Path) -> Path:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow is not installed")
    width = int(config.width)
    height = int(config.height)
    margin = 32
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    font_path = find_word_cloud_font()
    placed = layout_words(draw, words, width, height, margin, font_path)
    for item in placed:
        font = load_font(font_path, int(item["size"]))
        draw.text((float(item["x"]), float(item["y"])), str(item["word"]), fill=str(item["color"]), font=font)

    footer_font = load_font(font_path, max(20, round(height * 0.053)))
    draw.text((42, height - 54), f"最近 {limit} 条热词云 | {valid_messages} 条有效消息", fill="#111827", font=footer_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return output_path


def layout_words(
    draw: Any,
    words: list[dict[str, Any]],
    width: int,
    height: int,
    margin: int,
    font_path: str | None,
) -> list[dict[str, Any]]:
    placed: list[dict[str, Any]] = []
    center_x = width / 2
    center_y = height / 2 - 28
    for original in words:
        item = dict(original)
        for attempt in range(4):
            item["size"] = max(10, int(original["size"]) - attempt * 4)
            font = load_font(font_path, int(item["size"]))
            text_width, text_height = measure_text(draw, str(item["word"]), font)
            item["width"] = text_width
            item["height"] = text_height
            if text_width > width - margin * 2:
                continue
            placed_item = False
            for tick in range(3600):
                angle = tick * 0.38
                radius = 5.2 * math.sqrt(tick)
                x = center_x + math.cos(angle) * radius - text_width / 2
                y = center_y + math.sin(angle) * radius - text_height / 2
                if x < margin or y < margin or x + text_width > width - margin or y + text_height > height - 78:
                    continue
                item["x"] = x
                item["y"] = y
                if overlaps(item, placed):
                    continue
                placed.append(dict(item))
                placed_item = True
                break
            if placed_item:
                break
    return placed


def overlaps(item: dict[str, Any], placed: list[dict[str, Any]]) -> bool:
    padding = 4
    ax1 = float(item["x"]) - padding
    ay1 = float(item["y"]) - padding
    ax2 = float(item["x"]) + float(item["width"]) + padding
    ay2 = float(item["y"]) + float(item["height"]) + padding
    for other in placed:
        bx1 = float(other["x"]) - padding
        by1 = float(other["y"]) - padding
        bx2 = float(other["x"]) + float(other["width"]) + padding
        by2 = float(other["y"]) + float(other["height"]) + padding
        if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
            return True
    return False


def measure_text(draw: Any, text: str, font: Any) -> tuple[float, float]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])


def load_font(font_path: str | None, size: int) -> Any:
    if ImageFont is None:
        raise RuntimeError("Pillow is not installed")
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            logger.debug("Failed to load word cloud font: %s", font_path, exc_info=True)
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def find_word_cloud_font() -> str | None:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
    ]
    for value in candidates:
        if Path(value).exists():
            return value
    fc_match = shutil.which("fc-match")
    if fc_match:
        try:
            output = subprocess.check_output([fc_match, "-f", "%{file}", "sans:lang=zh-cn"], text=True, timeout=2).strip()
            if output and Path(output).exists():
                return output
        except Exception:
            logger.debug("fc-match did not return a usable CJK font", exc_info=True)
    return None


def extract_word_cloud_prompt(text: str, config: WordCloudConfig) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for prefix in sorted((item.strip() for item in config.command_prefixes if item.strip()), key=len, reverse=True):
        prefix_lower = prefix.lower()
        if lowered == prefix_lower:
            return ""
        if lowered.startswith(prefix_lower + " ") or lowered.startswith(prefix_lower + "\n"):
            return stripped[len(prefix) :].strip()
    return None


def parse_word_cloud_limit(prompt: str, config: WordCloudConfig) -> int:
    match = re.search(r"\d+", prompt or "")
    if not match:
        return int(config.default_limit)
    value = int(match.group(0))
    return max(int(config.min_limit), min(value, int(config.max_limit)))


def format_word_cloud_status(text: str) -> str:
    return f"☁️ <b>词云</b>\n{html.escape(text)}"


def word_cloud_config_from_dict(data: dict[str, Any]) -> WordCloudConfig:
    defaults = WordCloudConfig()
    max_limit = max(50, min(int(data.get("max_limit") or defaults.max_limit), 10000))
    min_limit = max(10, min(int(data.get("min_limit") or defaults.min_limit), max_limit))
    return WordCloudConfig(
        command_prefixes=_list_or_default(data.get("command_prefixes"), defaults.command_prefixes),
        default_limit=max(min_limit, min(int(data.get("default_limit") or defaults.default_limit), max_limit)),
        max_limit=max_limit,
        min_limit=min_limit,
        output_dir=str(data.get("output_dir") or defaults.output_dir),
        width=max(480, min(int(data.get("width") or defaults.width), 2400)),
        height=max(360, min(int(data.get("height") or defaults.height), 1800)),
        delete_command=bool(data.get("delete_command", defaults.delete_command)),
        ignore_command_prefixes=_list_or_default(data.get("ignore_command_prefixes"), defaults.ignore_command_prefixes),
        stop_words=_list_or_default(data.get("stop_words"), defaults.stop_words),
    )


def _list_or_default(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(default)
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    return cleaned or list(default)


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


def _safe_chat_id(chat_id: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(chat_id))
