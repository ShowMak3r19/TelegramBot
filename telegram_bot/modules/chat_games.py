from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram_bot.config import (
    ChatGamesConfig,
    EmojiRiddleItemConfig,
    GarbledDecodeConfig,
    TimedImageGameConfig,
    _chat_games_config_from_dict,
)
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.telegram_io import (
    event_message,
    is_outgoing,
    message_text,
    safe_delete_message,
)

from .base import ModuleCard

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover - Pillow is declared in requirements.
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]


@dataclass
class CorrectAnswer:
    message: Any
    sender_id: str
    text: str
    received_at: float


@dataclass
class ActiveGame:
    game_id: str
    kind: str
    chat_id: Any
    client: Any
    answer_set: set[str]
    display_answer: str
    reward_text: str
    winner_policy: str
    announce_answer: bool
    prompt_message_id: int | None
    prompt_caption: str
    ends_at: float
    correct: list[CorrectAnswer] = field(default_factory=list)
    correct_sender_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class DecodeStart:
    reward_text: str
    phrase: str | None = None


class ChatGamesModule:
    def __init__(self, card: ModuleCard, config: ChatGamesConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.state_path = self._resolve_path(self.config.state_store)
        self.output_dir = self._resolve_path(self.config.output_dir)
        self.state = self._load_state()
        self.active_games: dict[str, ActiveGame] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._sync_card_config()

    async def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self.active_games.clear()

    async def handle_message(self, event: Any) -> HandlerResult:
        message = event_message(event)
        text = message_text(message)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        if chat_id is None or not text:
            return HandlerResult.ignored(self.card.id)
        if _is_edited_message(message):
            return HandlerResult.ignored(self.card.id)

        if await self._record_active_game_answer(event, message, text, chat_id):
            return HandlerResult.handled(self.card.id, "game answer accepted")

        if is_outgoing(event):
            emoji_reward = extract_command_reward(text, self.config.emoji_riddle.command_prefixes, self.config.emoji_riddle.reward_text)
            if emoji_reward is not None:
                await self._start_emoji_riddle(event, emoji_reward)
                return HandlerResult.handled(self.card.id, "emoji riddle started")
            decode_start = extract_decode_start(
                text,
                self.config.garbled_decode.command_prefixes,
                self.config.garbled_decode.reward_text,
            )
            if decode_start is not None:
                await self._start_garbled_decode(event, decode_start)
                return HandlerResult.handled(self.card.id, "garbled decode started")
            return HandlerResult.ignored(self.card.id)

        if await self._maybe_award_lucky_word(event, message, text, chat_id):
            return HandlerResult.handled(self.card.id, "lucky word awarded")

        return HandlerResult.ignored(self.card.id)

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("chat_games", values)
        if not isinstance(data, dict):
            return
        self.config = _chat_games_config_from_dict({**asdict(self.config), **data})
        self.state_path = self._resolve_path(self.config.state_store)
        self.output_dir = self._resolve_path(self.config.output_dir)
        self._sync_card_config()

    async def _start_emoji_riddle(self, event: Any, reward_text: str) -> None:
        cfg = self.config.emoji_riddle
        if not cfg.enabled:
            return
        items = [item for item in cfg.items if item.answers]
        if not items:
            return
        item = random.choice(items)
        answers = {_normalize_answer(answer) for answer in item.answers if _normalize_answer(answer)}
        await self._start_timed_image_game(
            event=event,
            cfg=cfg,
            kind="emoji_riddle",
            display_answer=item.answers[0],
            answer_set=answers,
            reward_text=reward_text,
            image_builder=lambda output: render_emoji_riddle_png(item, output),
            caption=build_emoji_riddle_caption(item, cfg.duration_seconds, reward_text),
        )

    async def _start_garbled_decode(self, event: Any, decode_start: DecodeStart) -> None:
        cfg = self.config.garbled_decode
        if not cfg.enabled:
            return
        phrase = (decode_start.phrase or "").strip()
        if not phrase:
            if not cfg.phrases:
                return
            phrase = random.choice(cfg.phrases).strip()
        if not phrase:
            return
        await self._start_timed_image_game(
            event=event,
            cfg=cfg,
            kind="garbled_decode",
            display_answer=phrase,
            answer_set={_normalize_answer(phrase)},
            reward_text=decode_start.reward_text,
            image_builder=lambda output: render_garbled_decode_png(phrase, output),
            caption=build_garbled_decode_caption(cfg.duration_seconds, decode_start.reward_text),
        )

    async def _start_timed_image_game(
        self,
        *,
        event: Any,
        cfg: TimedImageGameConfig,
        kind: str,
        display_answer: str,
        answer_set: set[str],
        reward_text: str,
        image_builder: Any,
        caption: str,
    ) -> None:
        message = event_message(event)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
        client = getattr(event, "client", None)
        if chat_id is None or client is None or not hasattr(client, "send_file"):
            return

        chat_key = _chat_key(chat_id)
        existing = self.active_games.get(chat_key)
        if existing and time.time() < existing.ends_at:
            if hasattr(client, "send_message"):
                await client.send_message(chat_id, "上一题还没开奖，稍等一下。", reply_to=getattr(message, "id", None))
            return

        if cfg.delete_command:
            await safe_delete_message(message, "chat_games_command")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        game_id = f"{kind}_{int(time.time() * 1000)}"
        output_path = self.output_dir / f"{game_id}_{_safe_chat_id(chat_id)}.png"
        await asyncio.to_thread(image_builder, output_path)
        sent = await client.send_file(
            chat_id,
            file=str(output_path),
            caption=caption,
            force_document=False,
            reply_to=None if cfg.delete_command else getattr(message, "id", None),
        )

        active = ActiveGame(
            game_id=game_id,
            kind=kind,
            chat_id=chat_id,
            client=client,
            answer_set=answer_set,
            display_answer=display_answer,
            reward_text=reward_text,
            winner_policy=cfg.winner_policy,
            announce_answer=cfg.announce_answer,
            prompt_message_id=getattr(sent, "id", None),
            prompt_caption=caption,
            ends_at=time.time() + max(0.1, float(cfg.duration_seconds)),
        )
        self.active_games[chat_key] = active
        task = asyncio.create_task(self._settle_game(chat_key, game_id), name=f"chat-game-{game_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self.card.metrics.update({"active_games": len(self.active_games), "last_started": kind})
        logger.info("Chat game started: kind=%s chat_id=%s answer=%s", kind, chat_id, display_answer)

    async def _record_active_game_answer(self, event: Any, message: Any, text: str, chat_id: Any) -> bool:
        if is_outgoing(event):
            return False
        active = self.active_games.get(_chat_key(chat_id))
        if active is None or time.time() > active.ends_at:
            return False
        normalized = _normalize_answer(text)
        if normalized not in active.answer_set:
            return False
        sender = str(getattr(message, "sender_id", getattr(event, "sender_id", "")) or "")
        if sender and sender in active.correct_sender_ids:
            return True
        answer = CorrectAnswer(message=message, sender_id=sender, text=text, received_at=time.time())
        active.correct.append(answer)
        if sender:
            active.correct_sender_ids.add(sender)
        self.card.metrics.update({"last_correct_answers": len(active.correct)})
        self.active_games.pop(_chat_key(chat_id), None)
        self.card.metrics.update({"active_games": len(self.active_games)})
        await self._award_game(active, answer)
        return True

    async def _settle_game(self, chat_key: str, game_id: str) -> None:
        try:
            active = self.active_games.get(chat_key)
            if active is None or active.game_id != game_id:
                return
            await asyncio.sleep(max(0.0, active.ends_at - time.time()))
            active = self.active_games.pop(chat_key, None)
            if active is None or active.game_id != game_id:
                return

            if active.correct:
                await self._award_game(active, choose_winner(active.correct, active.winner_policy))
            elif active.announce_answer:
                await self._mark_prompt(active, f"本轮无人答中\n答案：{active.display_answer}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat game settlement failed")
        finally:
            self.card.metrics.update({"active_games": len(self.active_games)})

    async def _award_game(self, active: ActiveGame, winner: CorrectAnswer) -> None:
        await active.client.send_message(
            active.chat_id,
            active.reward_text,
            reply_to=getattr(winner.message, "id", None),
        )
        self.card.metrics.update({"last_winner": winner.sender_id, "last_answer": active.display_answer})
        logger.info("Chat game awarded: kind=%s chat_id=%s sender=%s", active.kind, active.chat_id, winner.sender_id)
        if active.announce_answer:
            await self._mark_prompt(active, f"已答中\n答案：{active.display_answer}")

    async def _mark_prompt(self, active: ActiveGame, result_text: str) -> None:
        if active.prompt_message_id is None or not hasattr(active.client, "edit_message"):
            return
        text = f"{active.prompt_caption.rstrip()}\n\n{result_text.strip()}"
        try:
            await active.client.edit_message(active.chat_id, active.prompt_message_id, text, parse_mode=None)
        except Exception as exc:
            logger.warning(
                "Failed to mark chat game prompt: kind=%s chat_id=%s message_id=%s error=%s",
                active.kind,
                active.chat_id,
                active.prompt_message_id,
                exc,
            )

    async def _maybe_award_lucky_word(self, event: Any, message: Any, text: str, chat_id: Any) -> bool:
        cfg = self.config.lucky_word
        if not cfg.enabled or not cfg.words or cfg.daily_limit_per_chat <= 0:
            return False
        stripped = text.strip()
        if len(stripped) < cfg.min_message_length:
            return False
        if any(stripped.startswith(prefix) for prefix in cfg.ignore_command_prefixes if prefix):
            return False

        chat_key = _chat_key(chat_id)
        today = datetime.now().strftime("%Y-%m-%d")
        state = self._lucky_word_state(chat_key, today)
        award_count = int(state.get("award_count", 0) or 0)
        if award_count >= cfg.daily_limit_per_chat:
            return False

        sender = str(getattr(message, "sender_id", getattr(event, "sender_id", "")) or "")
        user_awards = state.setdefault("user_awards", {})
        if cfg.per_user_daily_limit > 0 and sender and int(user_awards.get(sender, 0) or 0) >= cfg.per_user_daily_limit:
            return False

        word = select_lucky_word(cfg.words, today, chat_key, award_count)
        if not lucky_word_matches(stripped, word):
            return False

        state["award_count"] = award_count + 1
        state.setdefault("matched_words", []).append(word)
        if sender:
            user_awards[sender] = int(user_awards.get(sender, 0) or 0) + 1
        self._save_state()

        client = getattr(event, "client", None)
        if client is not None and hasattr(client, "send_message"):
            await client.send_message(chat_id, cfg.reward_text, reply_to=getattr(message, "id", None))
        self.card.metrics.update({"lucky_word_hits": state["award_count"], "last_lucky_word": word})
        logger.info("Lucky word awarded: chat_id=%s sender=%s word=%s", chat_id, sender, word)
        return True

    def _lucky_word_state(self, chat_key: str, today: str) -> dict[str, Any]:
        root = self.state.setdefault("lucky_word", {})
        entry = root.get(chat_key)
        if not isinstance(entry, dict) or entry.get("date") != today:
            entry = {"date": today, "award_count": 0, "user_awards": {}, "matched_words": []}
            root[chat_key] = entry
        if not isinstance(entry.get("user_awards"), dict):
            entry["user_awards"] = {}
        if not isinstance(entry.get("matched_words"), list):
            entry["matched_words"] = []
        return entry

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"lucky_word": {}}
        try:
            with self.state_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load chat games state, starting empty")
            return {"lucky_word": {}}
        return data if isinstance(data, dict) else {"lucky_word": {}}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _sync_card_config(self) -> None:
        self.card.config = asdict(self.config)
        self.card.metrics.update(
            {
                "state_store": str(self.state_path),
                "output_dir": str(self.output_dir),
                "pillow": "available" if Image is not None else "missing",
                "active_games": len(self.active_games),
            }
        )

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        root = self.project_root or Path.cwd()
        return root / path


def choose_winner(correct: list[CorrectAnswer], winner_policy: str) -> CorrectAnswer:
    if winner_policy == "first":
        return min(correct, key=lambda item: item.received_at)
    return random.choice(correct)


def command_matches(text: str, prefixes: list[str]) -> bool:
    return extract_command_payload(text, prefixes) is not None


def extract_command_reward(text: str, prefixes: list[str], default_reward: str) -> str | None:
    payload = extract_command_payload(text, prefixes)
    if payload is None:
        return None
    match = _reward_match(payload)
    if match is None:
        return default_reward
    value = max(1, min(int(match.group(1)), 999999))
    return f"+{value}"


def extract_decode_start(text: str, prefixes: list[str], default_reward: str) -> DecodeStart | None:
    payload = extract_command_payload(text, prefixes)
    if payload is None:
        return None
    reward_text = default_reward
    match = _reward_match(payload)
    if match is not None:
        value = max(1, min(int(match.group(1)), 999999))
        reward_text = f"+{value}"
        payload = _strip_decode_payload(payload[: match.start()] + payload[match.end() :])
    return DecodeStart(reward_text=reward_text, phrase=payload or None)


def _reward_match(payload: str) -> re.Match[str] | None:
    return re.search(r"(?<![\w\u4e00-\u9fff])\+?\s*(\d{1,6})(?![\w\u4e00-\u9fff%])", payload)


def _strip_decode_payload(payload: str) -> str:
    return re.sub(r"^[\s,，:：|]+|[\s,，:：|]+$", "", payload)


def extract_command_payload(text: str, prefixes: list[str]) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for prefix in sorted((item.strip() for item in prefixes if item.strip()), key=len, reverse=True):
        candidate = prefix.lower()
        if lowered == candidate:
            return ""
        if lowered.startswith(candidate + " ") or lowered.startswith(candidate + "\n"):
            return stripped[len(prefix) :].strip()
    return None


def select_lucky_word(words: list[str], period: str, chat_key: str, award_count: int) -> str:
    seed = hashlib.sha256(f"{period}|{chat_key}|{award_count}|{len(words)}".encode("utf-8")).hexdigest()
    return random.Random(seed).choice(words)


def lucky_word_matches(text: str, word: str) -> bool:
    normalized_text = text.casefold()
    normalized_word = word.casefold().strip()
    return bool(normalized_word and normalized_word in normalized_text)


def build_emoji_riddle_caption(item: EmojiRiddleItemConfig, duration_seconds: float, reward_text: str) -> str:
    hint = f"\n提示：{item.hint}" if item.hint else ""
    return f"🧩 Emoji 图谜\n题面：{item.clue}{hint}\n{int(duration_seconds)} 秒内直接回复答案，第一个答中 {reward_text}。"


def build_garbled_decode_caption(duration_seconds: float, reward_text: str) -> str:
    return f"🔐 乱码解码\n图里藏着一句话，{int(duration_seconds)} 秒内直接回复原句，第一个答中 {reward_text}。"


def render_emoji_riddle_png(item: EmojiRiddleItemConfig, output_path: Path) -> Path:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is not installed")
    width, height = 960, 540
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font = load_font(42, prefer_emoji=False)
    clue_font = load_font(78, prefer_emoji=False)
    hint_font = load_font(30, prefer_emoji=False)

    draw.rounded_rectangle((28, 28, width - 28, height - 28), radius=26, fill="#ffffff", outline="#cbd5e1", width=3)
    draw.text((56, 54), "Emoji 图谜", fill="#0f172a", font=title_font)
    draw.text((56, 114), "看图猜词，直接在群里回复答案", fill="#475569", font=hint_font)
    draw_centered_mixed_text(image, item.clue, clue_font, width, 236, "#111827")
    if item.hint:
        draw_centered_text(draw, f"提示：{item.hint}", hint_font, width, 390, "#334155")
    draw.text((56, height - 70), "答对池开奖：+100", fill="#0f766e", font=hint_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return output_path


def _render_garbled_decode_png_legacy(phrase: str, output_path: Path) -> Path:
    if Image is None or ImageDraw is None or ImageFilter is None:
        raise RuntimeError("Pillow is not installed")
    seed = hashlib.sha256(f"{phrase}|{time.time_ns()}".encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    width, height = 960, 420
    base = Image.new("RGB", (width, height), "#f8fafc")
    text_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_layer)
    title_font = load_font(34, prefer_emoji=False)
    phrase_font = load_font(70, prefer_emoji=False)
    draw.text((42, 32), "乱码解码", fill="#0f172a", font=title_font)
    draw.text((42, 80), "切片错位了，但原句还在。", fill="#475569", font=load_font(26, prefer_emoji=False))
    draw_centered_text(draw, phrase, phrase_font, width, 200, "#111827")

    scrambled = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    strip_height = 18
    for y in range(132, height - 54, strip_height):
        offset = rng.randint(-22, 22)
        strip = text_layer.crop((0, y, width, min(y + strip_height, height)))
        if offset >= 0:
            scrambled.alpha_composite(strip, (offset, y))
            if offset:
                scrambled.alpha_composite(strip.crop((0, 0, offset, strip.height)), (0, y))
        else:
            scrambled.alpha_composite(strip.crop((-offset, 0, width, strip.height)), (0, y))
            scrambled.alpha_composite(strip.crop((width + offset, 0, width, strip.height)), (width + offset, y))

    base = Image.alpha_composite(base.convert("RGBA"), scrambled)
    draw = ImageDraw.Draw(base)
    for _ in range(42):
        x1 = rng.randint(30, width - 30)
        y1 = rng.randint(130, height - 44)
        x2 = min(width - 30, x1 + rng.randint(24, 120))
        color = rng.choice(["#94a3b8", "#cbd5e1", "#67e8f9", "#a7f3d0", "#fde68a"])
        draw.line((x1, y1, x2, y1 + rng.randint(-8, 8)), fill=color, width=rng.randint(1, 3))
    for _ in range(36):
        draw.text(
            (rng.randint(48, width - 80), rng.randint(140, height - 70)),
            rng.choice("乱码解码答案隐藏噪声0123456789"),
            fill=rng.choice(["#cbd5e1", "#e2e8f0", "#bae6fd"]),
            font=load_font(rng.randint(18, 30), prefer_emoji=False),
        )
    base = base.filter(ImageFilter.GaussianBlur(radius=0.35))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(output_path, format="PNG")
    return output_path


def render_garbled_decode_png(phrase: str, output_path: Path) -> Path:
    if Image is None or ImageDraw is None or ImageFilter is None:
        raise RuntimeError("Pillow is not installed")
    seed = hashlib.sha256(f"{phrase}|{time.time_ns()}".encode("utf-8")).hexdigest()
    rng = random.Random(seed)
    display_phrase = spaced_garbled_text(emoji_safe_text(phrase))
    width, height = 960, 420
    base = Image.new("RGB", (width, height), "#f8fafc")
    text_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_layer)
    title_font = load_font(34, prefer_emoji=False)
    phrase_font = load_font(68, prefer_emoji=False)
    draw.text((42, 32), "乱码解码", fill="#0f172a", font=title_font)
    draw.text((42, 80), "切片和浅噪声会打乱原句，但主体仍可辨认。", fill="#475569", font=load_font(26, prefer_emoji=False))
    draw_centered_text(draw, display_phrase, phrase_font, width, 178, "#0f172a")

    scrambled = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    strip_height = 18
    for y in range(118, height - 34, strip_height):
        offset = rng.randint(-16, 16)
        strip = text_layer.crop((0, y, width, min(y + strip_height, height)))
        if rng.random() < 0.2:
            strip = strip.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.08, 0.24)))
        if offset >= 0:
            scrambled.alpha_composite(strip, (offset, y))
            if offset:
                scrambled.alpha_composite(strip.crop((0, 0, offset, strip.height)), (0, y))
        else:
            scrambled.alpha_composite(strip.crop((-offset, 0, width, strip.height)), (0, y))
            scrambled.alpha_composite(strip.crop((width + offset, 0, width, strip.height)), (width + offset, y))
        if rng.random() < 0.08:
            ghost = strip.copy()
            ghost.putalpha(ghost.getchannel("A").point(lambda value: int(value * rng.uniform(0.08, 0.14))))
            scrambled.alpha_composite(ghost, (rng.randint(-20, 20), y + rng.randint(-2, 3)))

    base = Image.alpha_composite(base.convert("RGBA"), scrambled)
    shadow_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    shadow_font = load_font(64, prefer_emoji=False)
    for fill, dx, dy in (("#38bdf826", -4, -1), ("#f9731624", 5, 2)):
        shadow_draw = ImageDraw.Draw(shadow_layer)
        bbox = shadow_draw.textbbox((0, 0), display_phrase, font=shadow_font)
        shadow_draw.text(((width - (bbox[2] - bbox[0])) / 2 + dx, 180 + dy), display_phrase, fill=fill, font=shadow_font)
    base = Image.alpha_composite(base, shadow_layer.filter(ImageFilter.GaussianBlur(radius=0.55)))

    draw = ImageDraw.Draw(base)
    center_band = (145, 300)
    for _ in range(38):
        x1 = rng.randint(30, width - 30)
        y1 = rng.randint(116, height - 34)
        if center_band[0] <= y1 <= center_band[1] and rng.random() < 0.55:
            y1 = _random_outer_y(rng, 116, height - 34, center_band)
        x2 = min(width - 30, x1 + rng.randint(28, 130))
        color = rng.choice(["#64748b55", "#94a3b85c", "#06b6d45f", "#10b9814f", "#f59e0b58"])
        draw.line((x1, y1, x2, y1 + rng.randint(-10, 10)), fill=color, width=rng.randint(1, 2))
    noise_chars = "乱码解码答案隐藏噪声0123456789▒░▓#%?"
    for _ in range(44):
        y = rng.randint(124, height - 70)
        if center_band[0] <= y <= center_band[1] and rng.random() < 0.62:
            y = _random_outer_y(rng, 124, height - 70, center_band)
        draw.text(
            (rng.randint(48, width - 80), y),
            rng.choice(noise_chars),
            fill=rng.choice(["#94a3b866", "#cbd5e184", "#bae6fd7a", "#ddd6fe66"]),
            font=load_font(rng.randint(16, 26), prefer_emoji=False),
        )
    base = base.filter(ImageFilter.GaussianBlur(radius=0.22))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(output_path, format="PNG")
    return output_path


@dataclass(frozen=True)
class _MixedTextItem:
    text: str
    kind: str
    width: int
    height: int


def draw_centered_mixed_text(image: Any, text: str, font: Any, width: int, y: int, fill: str, *, x_offset: int = 0) -> None:
    draw = ImageDraw.Draw(image)
    items = _mixed_text_items(text, font)
    total_width = sum(item.width for item in items)
    x = (width - total_width) / 2 + x_offset
    for item in items:
        if item.kind == "emoji":
            _draw_emoji_token(draw, item.text, int(x), y - 8, item.width, item.height)
        else:
            draw.text((x, y), item.text, fill=fill, font=font)
        x += item.width


def _mixed_text_items(text: str, font: Any) -> list[_MixedTextItem]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    items: list[_MixedTextItem] = []
    pending = ""
    for cluster in _grapheme_clusters(text):
        if _is_emoji_cluster(cluster):
            if pending:
                items.append(_text_item(draw, pending, font))
                pending = ""
            items.append(_emoji_item(cluster, font))
        else:
            pending += cluster
    if pending:
        items.append(_text_item(draw, pending, font))
    return items


def emoji_safe_text(text: str) -> str:
    parts: list[str] = []
    for cluster in _grapheme_clusters(text):
        parts.append(_emoji_fallback_label(cluster) if _is_emoji_cluster(cluster) else cluster)
    return "".join(parts)


def spaced_garbled_text(text: str) -> str:
    chunks = re.findall(r"[A-Za-z0-9]+|.", text)
    return " ".join(chunk for chunk in chunks if chunk.strip())


def _random_outer_y(rng: random.Random, low: int, high: int, blocked: tuple[int, int]) -> int:
    ranges = []
    if low <= blocked[0] - 8:
        ranges.append((low, blocked[0] - 8))
    if blocked[1] + 8 <= high:
        ranges.append((blocked[1] + 8, high))
    if not ranges:
        return rng.randint(low, high)
    start, end = rng.choice(ranges)
    return rng.randint(start, end)


def _text_item(draw: Any, text: str, font: Any) -> _MixedTextItem:
    bbox = draw.textbbox((0, 0), text, font=font)
    return _MixedTextItem(text=text, kind="text", width=max(1, bbox[2] - bbox[0]), height=max(1, bbox[3] - bbox[1]))


def _emoji_item(text: str, font: Any) -> _MixedTextItem:
    size = max(42, int(getattr(font, "size", 72) * 0.95))
    width = max(size, int(size * (0.78 + 0.2 * max(1, len(_strip_variation(text))))))
    return _MixedTextItem(text=text, kind="emoji", width=width + 8, height=size)


def _draw_emoji_token(draw: Any, text: str, x: int, y: int, width: int, height: int) -> None:
    label = _emoji_fallback_label(text)
    radius = max(12, height // 5)
    draw.rounded_rectangle(
        (x + 2, y + 2, x + width - 4, y + height + 10),
        radius=radius,
        fill="#ecfeff",
        outline="#67e8f9",
        width=3,
    )
    token_font = load_font(max(24, min(42, int(height * 0.42))), prefer_emoji=False)
    bbox = draw.textbbox((0, 0), label, font=token_font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(
        (x + (width - text_width) / 2, y + (height - text_height) / 2 + 2),
        label,
        fill="#0f172a",
        font=token_font,
    )


def _emoji_fallback_label(text: str) -> str:
    mapping = {
        "🌧": "雨",
        "🏠": "屋",
        "🐟": "鱼",
        "🔥": "火",
        "🧊": "冰",
        "🐔": "鸡",
        "🌶": "辣",
        "🛫": "飞",
        "🥚": "蛋",
        "💥": "爆",
        "👀": "眼",
        "👂": "耳",
        "👃": "鼻",
        "👅": "舌",
        "🐎": "马",
        "🐯": "虎",
        "🧠": "脑",
        "⚡": "电",
        "💡": "灯",
        "🌙": "月",
        "👴": "老",
        "❤️": "心",
        "❤": "心",
        "📱": "机",
        "🔋": "电",
    }
    stripped = _strip_variation(text)
    if stripped in mapping:
        return mapping[stripped]
    if text in mapping:
        return mapping[text]
    for char in stripped:
        if char in mapping:
            return mapping[char]
    return "图"


def _grapheme_clusters(text: str) -> list[str]:
    clusters: list[str] = []
    current = ""
    for char in text:
        code = ord(char)
        if not current:
            current = char
            continue
        if code in {0xFE0E, 0xFE0F, 0x200D} or 0x1F3FB <= code <= 0x1F3FF:
            current += char
            continue
        if current.endswith("\u200d"):
            current += char
            continue
        clusters.append(current)
        current = char
    if current:
        clusters.append(current)
    return clusters


def _is_emoji_cluster(text: str) -> bool:
    return any(_is_emoji_codepoint(ord(char)) for char in _strip_variation(text))


def _is_emoji_codepoint(code: int) -> bool:
    return 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or code == 0x2764


def _strip_variation(text: str) -> str:
    return text.replace("\ufe0f", "").replace("\ufe0e", "").replace("\u200d", "")


def draw_centered_text(draw: Any, text: str, font: Any, width: int, y: int, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text(((width - text_width) / 2, y), text, fill=fill, font=font)


def load_font(size: int, *, prefer_emoji: bool) -> Any:
    if ImageFont is None:
        raise RuntimeError("Pillow is not installed")
    for font_path in find_font_candidates(prefer_emoji):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            logger.debug("Failed to load font: %s", font_path, exc_info=True)
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def find_font_candidates(prefer_emoji: bool) -> list[str]:
    emoji_candidates = [
        r"C:\Windows\Fonts\seguiemj.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
    ]
    text_candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    ordered = (emoji_candidates + text_candidates) if prefer_emoji else text_candidates + emoji_candidates
    existing = [value for value in ordered if Path(value).exists()]
    fc_match = shutil.which("fc-match")
    if fc_match:
        try:
            query = "emoji" if prefer_emoji else "sans:lang=zh-cn"
            output = subprocess.check_output([fc_match, "-f", "%{file}", query], text=True, timeout=2).strip()
            if output and Path(output).exists():
                existing.append(output)
        except Exception:
            logger.debug("fc-match did not return a usable font", exc_info=True)
    return existing


def _normalize_answer(text: str) -> str:
    lowered = emoji_safe_text(text or "").casefold()
    return re.sub(r"[\s\W_]+", "", lowered, flags=re.UNICODE)


def _is_edited_message(message: Any) -> bool:
    return bool(getattr(message, "edit_date", None))


def _chat_key(chat_id: Any) -> str:
    return str(chat_id).strip()


def _safe_chat_id(chat_id: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", str(chat_id))
