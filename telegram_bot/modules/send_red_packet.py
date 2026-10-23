from __future__ import annotations

import json
import logging
import random
import re
import string
import time
import html
import asyncio
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from telegram_bot.config import SendRedPacketConfig, SendRedPacketTemplateConfig
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)

PACKET_LIST_COMMANDS = {"\u7ea2\u5305\u5217\u8868", "/\u7ea2\u5305\u5217\u8868"}
CANCEL_PACKET_COMMANDS = {"\u64a4\u9500\u7ea2\u5305", "/\u64a4\u9500\u7ea2\u5305"}
TRANSFER_MESSAGE_DELETE_SECONDS = 30.0
MIN_PACKET_AMOUNT = 2
STRICT_MIN_PACKET_AMOUNT = 101
STRICT_MIN_PACKET_GROUP_IDS: set[str] = set()


@dataclass
class PacketClaim:
    sender_id: str
    name: str
    amount: int
    message_id: str = ""


@dataclass
class ActivePacket:
    id: str
    template_id: str
    template_name: str
    template_type: str
    chat_id: str
    creator_id: str
    creator_name: str
    total_amount: int
    packet_count: int
    passphrase: str
    allocations: list[int]
    claims: list[PacketClaim] = field(default_factory=list)
    created_at: float = 0.0
    announcement_message_id: str = ""
    quiz_question: str = ""
    quiz_explanation: str = ""


@dataclass
class MathQuiz:
    question: str
    answer: str
    explanation: str
    kind: str


class SendRedPacketModule:
    def __init__(
        self,
        card: ModuleCard,
        config: SendRedPacketConfig,
        project_root: Path | None = None,
        rng: random.Random | None = None,
        now_func: Any = time.time,
        transfer_message_delete_seconds: float | None = TRANSFER_MESSAGE_DELETE_SECONDS,
    ) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.rng = rng or random.Random()
        self.now_func = now_func
        self.transfer_message_delete_seconds = None if transfer_message_delete_seconds is None else max(0.0, float(transfer_message_delete_seconds))
        self.state_path = self._resolve_path(self.config.state_store)
        self.active_packets = self._load_state()
        self._claim_lock = asyncio.Lock()
        self._sync_card_config()

    async def start(self) -> None:
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        message = _event_message(event)
        text = _message_text(message or event)
        if not text:
            return HandlerResult.ignored(self.card.id)

        if _is_outgoing(event):
            cancel_packet_id = parse_cancel_packet_command(text)
            if cancel_packet_id:
                await safe_delete_message(message, "cancel send red packet command")
                return await self._cancel_packet(event, cancel_packet_id)
            if is_packet_list_command(text):
                await safe_delete_message(message, "send red packet list command")
                return await self._send_packet_list(event)
            template, command = self.match_create_command(text)
            if template is None:
                return HandlerResult.ignored(self.card.id)
            if command is None:
                return HandlerResult.ignored(self.card.id)
            await safe_delete_message(message, "send red packet command")
            return await self._create_packet(event, template, command)

        packet = self._find_claimable_packet(event, text)
        if packet is None:
            return HandlerResult.ignored(self.card.id)
        return await self._claim_packet(event, packet)

    def match_create_command(self, text: str) -> tuple[SendRedPacketTemplateConfig | None, dict[str, Any] | None]:
        for template in self.config.templates:
            if not template.enabled:
                continue
            command = parse_template_command(text, template)
            if command is not None:
                return template, command
        return None, None

    async def _create_packet(self, event: Any, template: SendRedPacketTemplateConfig, command: dict[str, Any]) -> HandlerResult:
        message = _event_message(event)
        if template.type == "math_quiz":
            return await self._create_math_quiz(event, template, command)
        if template.type != "lucky_text":
            error = f"\u7ea2\u5305\u6a21\u677f\u7c7b\u578b\u6682\u4e0d\u652f\u6301\uff1a{template.type}"
            await reply_to_message(event, error)
            return HandlerResult.handled(self.card.id, "unsupported send red packet template", {"template_id": template.id, "error": error})
        total_amount = int(command["total_amount"])
        packet_count = int(command["packet_count"])
        passphrase = str(command["passphrase"]).strip()
        chat_id = str(getattr(message, "chat_id", getattr(event, "chat_id", "")))
        min_packet_amount = self._minimum_packet_amount(chat_id)
        error = validate_packet_request(total_amount, packet_count, passphrase, template.max_packet_count, min_packet_amount)
        if error:
            await reply_to_message(event, error)
            return HandlerResult.handled(self.card.id, "invalid send red packet command", {"error": error})

        self._trim_active_packets()
        packet = ActivePacket(
            id=self._new_packet_id(),
            template_id=template.id,
            template_name=template.name or "\u62fc\u624b\u6c14\u7ea2\u5305",
            template_type=template.type,
            chat_id=chat_id,
            creator_id=_sender_id(message or event),
            creator_name=await sender_display_name(event),
            total_amount=total_amount,
            packet_count=packet_count,
            passphrase=passphrase,
            allocations=split_amounts(total_amount, packet_count, self.rng, min_packet_amount=min_packet_amount),
            created_at=self.now_func(),
        )
        sent = await reply_to_message(event, format_packet_announcement(packet), parse_mode="html")
        packet.announcement_message_id = str(getattr(sent, "id", "") or "")
        self.active_packets[packet.id] = packet
        self._save_state()
        logger.info(
            "Send red packet created: id=%s chat_id=%s total=%s count=%s passphrase=%s",
            packet.id,
            packet.chat_id,
            packet.total_amount,
            packet.packet_count,
            _preview(packet.passphrase),
        )
        return HandlerResult.handled(
            self.card.id,
            "send red packet created",
            {
                "packet_id": packet.id,
                "template_id": template.id,
                "total_amount": total_amount,
                "packet_count": packet_count,
                "min_packet_amount": min_packet_amount,
            },
        )

    async def _create_math_quiz(self, event: Any, template: SendRedPacketTemplateConfig, command: dict[str, Any]) -> HandlerResult:
        message = _event_message(event)
        reward_amount = int(command.get("reward_amount") or 0)
        chat_id = str(getattr(message, "chat_id", getattr(event, "chat_id", "")))
        min_packet_amount = self._minimum_packet_amount(chat_id)
        error = validate_math_quiz_request(reward_amount, min_packet_amount)
        if error:
            await reply_to_message(event, error)
            return HandlerResult.handled(self.card.id, "invalid math quiz command", {"error": error})

        quiz = generate_math_quiz(self.rng)
        self._trim_active_packets()
        packet = ActivePacket(
            id=self._new_packet_id(),
            template_id=template.id,
            template_name=template.name or "\u8da3\u5473\u7b97\u672f\u9898",
            template_type=template.type,
            chat_id=chat_id,
            creator_id=_sender_id(message or event),
            creator_name=await sender_display_name(event),
            total_amount=reward_amount,
            packet_count=1,
            passphrase=normalize_answer(quiz.answer),
            allocations=[reward_amount],
            created_at=self.now_func(),
            quiz_question=quiz.question,
            quiz_explanation=quiz.explanation,
        )
        sent = await reply_to_message(event, format_math_quiz_announcement(packet), parse_mode="html")
        packet.announcement_message_id = str(getattr(sent, "id", "") or "")
        self.active_packets[packet.id] = packet
        self._save_state()
        logger.info(
            "Math quiz red packet created: id=%s chat_id=%s reward=%s answer=%s kind=%s",
            packet.id,
            packet.chat_id,
            packet.total_amount,
            _preview(packet.passphrase),
            quiz.kind,
        )
        return HandlerResult.handled(
            self.card.id,
            "math quiz red packet created",
            {
                "packet_id": packet.id,
                "template_id": template.id,
                "reward_amount": reward_amount,
                "min_packet_amount": min_packet_amount,
            },
        )

    async def _claim_packet(self, event: Any, packet: ActivePacket) -> HandlerResult:
        message = _event_message(event)
        sender_id = _sender_id(message or event)
        sender_name = await sender_display_name(event)
        async with self._claim_lock:
            active_packet = self.active_packets.get(packet.id)
            if active_packet is None:
                return HandlerResult.ignored(self.card.id)
            if not sender_id or sender_id == active_packet.creator_id:
                return HandlerResult.ignored(self.card.id)
            if any(claim.sender_id == sender_id for claim in active_packet.claims):
                logger.info("Send red packet duplicate claim ignored: id=%s sender_id=%s", active_packet.id, sender_id)
                return HandlerResult.ignored(self.card.id)
            claim_index = len(active_packet.claims)
            if claim_index >= len(active_packet.allocations):
                return HandlerResult.ignored(self.card.id)

            claim = PacketClaim(
                sender_id=sender_id,
                name=sender_name,
                amount=int(active_packet.allocations[claim_index]),
                message_id=str(getattr(message, "id", "")),
            )
            active_packet.claims.append(claim)
            completed = len(active_packet.claims) >= active_packet.packet_count
            if completed:
                self.active_packets.pop(active_packet.id, None)
            self._save_state()

        transfer_message = await reply_to_message(event, f"+{claim.amount}", reply_to=getattr(message, "id", None))
        self._schedule_transfer_message_delete(transfer_message, packet.id, claim.amount)
        logger.info("Send red packet claimed: id=%s sender_id=%s amount=%s", packet.id, sender_id, claim.amount)

        if completed:
            if packet.template_type == "math_quiz":
                await self._complete_math_quiz(event, packet, claim)
            else:
                await self._send_summary(event, packet)
            logger.info("Send red packet completed: id=%s claims=%s", packet.id, len(packet.claims))
        return HandlerResult.handled(
            self.card.id,
            "send red packet claimed",
            {"packet_id": packet.id, "amount": claim.amount, "completed": completed},
        )

    def _schedule_transfer_message_delete(self, message: Any, packet_id: str, amount: int) -> None:
        if self.transfer_message_delete_seconds is None or message is None or not hasattr(message, "delete"):
            return
        asyncio.create_task(self._delete_transfer_message_after_delay(message, packet_id, amount))

    async def _delete_transfer_message_after_delay(self, message: Any, packet_id: str, amount: int) -> None:
        try:
            if self.transfer_message_delete_seconds:
                await asyncio.sleep(self.transfer_message_delete_seconds)
            await safe_delete_message(message, "transfer message auto delete")
            logger.info(
                "Send red packet transfer message auto deleted: id=%s amount=%s delay_seconds=%s",
                packet_id,
                amount,
                self.transfer_message_delete_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to auto delete send red packet transfer message: id=%s amount=%s", packet_id, amount)

    async def _send_summary(self, event: Any, packet: ActivePacket) -> None:
        summary = format_packet_summary(packet)
        reply_to = int(packet.announcement_message_id) if packet.announcement_message_id.isdigit() else None
        try:
            await reply_to_message(event, summary, reply_to=reply_to, parse_mode="html")
        except Exception:
            logger.exception("Failed to send red packet summary as reply, sending without reply target")
            await reply_to_message(event, summary, parse_mode="html")

    async def _complete_math_quiz(self, event: Any, packet: ActivePacket, claim: PacketClaim) -> None:
        text = format_math_quiz_completed(packet, claim)
        edited = await safe_edit_message_by_id(event, packet.announcement_message_id, text, parse_mode="html")
        if not edited:
            await reply_to_message(event, text, parse_mode="html")

    async def _send_packet_list(self, event: Any) -> HandlerResult:
        message = _event_message(event)
        packets = self._list_unfinished_packets(event)
        await reply_to_message(event, format_packet_list(packets), parse_mode="html")
        logger.info("Send red packet active list requested: chat_id=%s count=%s", _chat_id(event), len(packets))
        return HandlerResult.handled(
            self.card.id,
            "send red packet list",
            {"active_count": len(packets)},
        )

    async def _cancel_packet(self, event: Any, packet_id: str) -> HandlerResult:
        packet = self._find_cancellable_packet(event, packet_id)
        if packet is None:
            await reply_to_message(event, f"\u672a\u627e\u5230\u5f53\u524d\u7fa4\u7684\u672a\u5b8c\u6210\u7ea2\u5305\uff1a<code>{html.escape(packet_id)}</code>", parse_mode="html")
            logger.info("Send red packet cancel requested but packet not found: chat_id=%s id=%s", _chat_id(event), packet_id)
            return HandlerResult.handled(self.card.id, "send red packet cancel not found", {"packet_id": packet_id, "cancelled": False})

        self.active_packets.pop(packet.id, None)
        self._save_state()
        edited = await safe_edit_message_by_id(event, packet.announcement_message_id, format_packet_cancelled(packet), parse_mode="html")
        if not edited:
            await reply_to_message(event, f"\u2705 \u5df2\u64a4\u9500\u7ea2\u5305 <code>{html.escape(packet.id)}</code>", parse_mode="html")
        logger.info("Send red packet cancelled: id=%s chat_id=%s type=%s claims=%s", packet.id, packet.chat_id, packet.template_type, len(packet.claims))
        return HandlerResult.handled(
            self.card.id,
            "send red packet cancelled",
            {"packet_id": packet.id, "template_type": packet.template_type, "cancelled": True},
        )

    def _list_unfinished_packets(self, event: Any) -> list[ActivePacket]:
        chat_id = _chat_id(event)
        packets = [
            packet
            for packet in self.active_packets.values()
            if packet.chat_id == chat_id and len(packet.claims) < packet.packet_count
        ]
        return sorted(packets, key=lambda item: item.created_at)

    def _find_cancellable_packet(self, event: Any, packet_id: str) -> ActivePacket | None:
        chat_id = _chat_id(event)
        normalized = normalize_packet_id(packet_id)
        for packet in self.active_packets.values():
            if packet.chat_id == chat_id and normalize_packet_id(packet.id) == normalized and len(packet.claims) < packet.packet_count:
                return packet
        return None

    def _find_claimable_packet(self, event: Any, text: str) -> ActivePacket | None:
        message = _event_message(event)
        chat_id = _chat_id(event)
        normalized = text.strip()
        if not normalized:
            return None
        candidates = [
            packet
            for packet in self.active_packets.values()
            if packet.chat_id == chat_id and is_packet_claim_text(packet, normalized) and len(packet.claims) < packet.packet_count
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.created_at)[0]

    def update_config(self, values: dict[str, Any]) -> None:
        if isinstance(values.get("templates"), list):
            self.config.templates = [
                template_from_dict(item)
                for item in values["templates"]
                if isinstance(item, dict)
            ]
        if "state_store" in values:
            self.config.state_store = str(values.get("state_store") or "runtime/data/send_red_packet_state.json")
            self.state_path = self._resolve_path(self.config.state_store)
            self.active_packets = self._load_state()
        if "id_length" in values:
            self.config.id_length = max(4, min(int(values.get("id_length") or 6), 12))
        if "max_active_packets" in values:
            self.config.max_active_packets = max(1, min(int(values.get("max_active_packets") or 20), 200))
        if "min_packet_amount" in values:
            self.config.min_packet_amount = max(2, min(int(values.get("min_packet_amount") or MIN_PACKET_AMOUNT), 1_000_000))
        if "strict_min_packet_amount" in values:
            self.config.strict_min_packet_amount = max(
                2,
                min(int(values.get("strict_min_packet_amount") or STRICT_MIN_PACKET_AMOUNT), 1_000_000),
            )
        if "strict_min_packet_group_ids" in values:
            self.config.strict_min_packet_group_ids = clean_list(values.get("strict_min_packet_group_ids"))
        self._trim_active_packets()
        self._sync_card_config()
        logger.info("Send red packet config updated: templates=%s active=%s", len(self.config.templates), len(self.active_packets))

    def _minimum_packet_amount(self, chat_id: str) -> int:
        return minimum_packet_amount_for_chat(self.config, chat_id)

    def _sync_card_config(self) -> None:
        self.card.config = {
            **asdict(self.config),
            "active_packet_count": len(self.active_packets),
        }

    def _trim_active_packets(self) -> None:
        limit = max(1, int(self.config.max_active_packets or 20))
        if len(self.active_packets) <= limit:
            return
        ordered = sorted(self.active_packets.values(), key=lambda item: item.created_at, reverse=True)
        self.active_packets = {packet.id: packet for packet in ordered[:limit]}

    def _new_packet_id(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        length = max(4, min(int(self.config.id_length or 6), 12))
        existing = set(self.active_packets)
        for _ in range(100):
            packet_id = "".join(self.rng.choice(alphabet) for _ in range(length))
            if packet_id not in existing:
                return packet_id
        return str(int(self.now_func() * 1000))[-length:]

    def _load_state(self) -> dict[str, ActivePacket]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load send red packet state, starting empty")
            return {}
        packets = data.get("active_packets", []) if isinstance(data, dict) else []
        loaded: dict[str, ActivePacket] = {}
        if not isinstance(packets, list):
            return loaded
        for item in packets:
            packet = packet_from_dict(item)
            if packet and len(packet.claims) < packet.packet_count:
                loaded[packet.id] = packet
        return loaded

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "active_packets": [packet_to_dict(packet) for packet in self.active_packets.values()],
        }
        self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self._sync_card_config()

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute() or self.project_root is None:
            return path
        return self.project_root / path


def parse_create_command(text: str, prefixes: list[str]) -> dict[str, Any] | None:
    stripped = text.strip()
    for prefix in prefixes:
        prefix = prefix.strip()
        if not prefix:
            continue
        if stripped == prefix:
            return {"total_amount": 0, "packet_count": 0, "passphrase": ""}
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix) :].strip()
        match = re.match(r"^(\d+)\s+(\d+)\s+(.+)$", rest, flags=re.DOTALL)
        if not match:
            return {"total_amount": 0, "packet_count": 0, "passphrase": ""}
        return {
            "total_amount": int(match.group(1)),
            "packet_count": int(match.group(2)),
            "passphrase": " ".join(match.group(3).split()),
        }
    return None


def parse_template_command(text: str, template: SendRedPacketTemplateConfig) -> dict[str, Any] | None:
    if template.type == "math_quiz":
        return parse_math_quiz_command(text, template.command_prefixes)
    return parse_create_command(text, template.command_prefixes)


def parse_math_quiz_command(text: str, prefixes: list[str]) -> dict[str, Any] | None:
    stripped = text.strip()
    for prefix in prefixes:
        prefix = prefix.strip()
        if not prefix:
            continue
        if stripped == prefix:
            return {"reward_amount": 0}
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix) :].strip()
        match = re.match(r"^(\d+)$", rest)
        if not match:
            return {"reward_amount": 0}
        return {"reward_amount": int(match.group(1))}
    return None


def is_packet_list_command(text: str) -> bool:
    return " ".join(text.split()) in PACKET_LIST_COMMANDS


def parse_cancel_packet_command(text: str) -> str | None:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None
    for command in sorted(CANCEL_PACKET_COMMANDS, key=len, reverse=True):
        if normalized == command:
            return ""
        prefix = command + " "
        if normalized.startswith(prefix):
            packet_id = normalized[len(prefix) :].strip()
            return normalize_packet_id(packet_id) if packet_id else ""
    return None


def normalize_packet_id(value: str) -> str:
    return str(value or "").strip().upper()


def minimum_packet_amount_for_chat(config: SendRedPacketConfig, chat_id: str) -> int:
    min_packet_amount = max(2, int(getattr(config, "min_packet_amount", MIN_PACKET_AMOUNT) or MIN_PACKET_AMOUNT))
    strict_min_packet_amount = max(
        min_packet_amount,
        int(getattr(config, "strict_min_packet_amount", STRICT_MIN_PACKET_AMOUNT) or STRICT_MIN_PACKET_AMOUNT),
    )
    strict_group_ids = clean_list(getattr(config, "strict_min_packet_group_ids", list(STRICT_MIN_PACKET_GROUP_IDS)))
    return strict_min_packet_amount if str(chat_id) in set(strict_group_ids) else min_packet_amount


def validate_packet_request(
    total_amount: int,
    packet_count: int,
    passphrase: str,
    max_packet_count: int,
    min_packet_amount: int = MIN_PACKET_AMOUNT,
) -> str:
    if total_amount <= 0 or packet_count <= 0 or not passphrase.strip():
        return "\u7ea2\u5305\u683c\u5f0f\uff1a\u7ea2\u5305 10000 10 \u54c8\u54c8\u54c8"
    if packet_count > max_packet_count:
        return f"\u7ea2\u5305\u6570\u91cf\u4e0d\u80fd\u8d85\u8fc7 {max_packet_count}"
    min_packet_amount = max(2, int(min_packet_amount or MIN_PACKET_AMOUNT))
    minimum_total = packet_count * min_packet_amount
    if total_amount < minimum_total:
        return f"\u7ea2\u5305\u603b\u989d\u4e0d\u80fd\u5c0f\u4e8e {minimum_total}\uff0c\u9700\u8981\u4fdd\u8bc1\u6bcf\u4e2a\u7ea2\u5305\u81f3\u5c11 {min_packet_amount}"
    return ""


def validate_math_quiz_request(reward_amount: int, min_packet_amount: int = MIN_PACKET_AMOUNT) -> str:
    if reward_amount <= 0:
        return "\u7b97\u672f\u9898\u683c\u5f0f\uff1a/math 6666"
    min_packet_amount = max(2, int(min_packet_amount or MIN_PACKET_AMOUNT))
    if reward_amount < min_packet_amount:
        return f"\u7b97\u672f\u9898\u5956\u52b1\u4e0d\u80fd\u5c0f\u4e8e {min_packet_amount}"
    return ""


def template_from_dict(data: dict[str, Any]) -> SendRedPacketTemplateConfig:
    return SendRedPacketTemplateConfig(
        id=str(data.get("id") or "").strip(),
        name=str(data.get("name") or "").strip(),
        type=str(data.get("type") or "lucky_text").strip(),
        enabled=bool(data.get("enabled", True)),
        command_prefixes=clean_list(data.get("command_prefixes")),
        max_packet_count=max(1, min(int(data.get("max_packet_count") or 100), 1000)),
    )


def clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def split_amounts(
    total_amount: int,
    packet_count: int,
    rng: random.Random | None = None,
    min_packet_amount: int = MIN_PACKET_AMOUNT,
) -> list[int]:
    rng = rng or random.Random()
    min_packet_amount = max(2, int(min_packet_amount or MIN_PACKET_AMOUNT))
    if packet_count <= 0:
        return []
    minimum_total = packet_count * min_packet_amount
    if total_amount < minimum_total:
        return []
    if packet_count == 1:
        return [total_amount]
    remaining = total_amount - minimum_total
    weights = [rng.random() for _ in range(packet_count)]
    weight_sum = sum(weights) or 1.0
    extras = [int(remaining * weight / weight_sum) for weight in weights]
    while sum(extras) < remaining:
        extras[rng.randrange(packet_count)] += 1
    while sum(extras) > remaining:
        index = rng.randrange(packet_count)
        if extras[index] > 0:
            extras[index] -= 1
    amounts = [extra + min_packet_amount for extra in extras]
    rng.shuffle(amounts)
    return amounts


def generate_math_quiz(rng: random.Random | None = None) -> MathQuiz:
    rng = rng or random.Random()
    generators = [
        _generate_sequence_quiz,
        _generate_emoji_algebra_quiz,
        _generate_logic_grid_quiz,
        _generate_emoji_calc_quiz,
        _generate_square_pattern_quiz,
    ]
    return rng.choice(generators)(rng)


def _generate_sequence_quiz(rng: random.Random) -> MathQuiz:
    start = rng.randint(1, 9)
    step = rng.randint(2, 6)
    seq = [start + step * index for index in range(5)]
    visible = "  ".join(str(value) for value in seq[:4])
    return MathQuiz(
        question=f"\u627e\u89c4\u5f8b\uff1a{visible}  ?",
        answer=str(seq[4]),
        explanation=f"\u89c4\u5f8b\uff1a\u7b49\u5dee +{step}\uff0c\u4e0b\u4e00\u4e2a\u6570\u662f {seq[4]}\u3002",
        kind="sequence",
    )


def _generate_emoji_algebra_quiz(rng: random.Random) -> MathQuiz:
    symbols = rng.sample(["\U0001f34e", "\U0001f34b", "\U0001f347", "\U0001f349", "\U0001f352"], 3)
    a, b, c = rng.sample(range(1, 10), 3)
    answer = a + b + c
    question = "\n".join(
        [
            f"{symbols[0]} + {symbols[1]} = {a + b}",
            f"{symbols[0]} + {symbols[2]} = {a + c}",
            f"{symbols[1]} + {symbols[2]} = {b + c}",
            f"{symbols[0]} + {symbols[1]} + {symbols[2]} = ?",
        ]
    )
    return MathQuiz(
        question=question,
        answer=str(answer),
        explanation=f"{symbols[0]}={a}\uff0c{symbols[1]}={b}\uff0c{symbols[2]}={c}\uff0c\u603b\u548c {answer}\u3002",
        kind="emoji_algebra",
    )


def _generate_logic_grid_quiz(rng: random.Random) -> MathQuiz:
    start = rng.randint(1, 8)
    values = [start + index for index in range(9)]
    missing_index = rng.randrange(9)
    rows: list[str] = []
    for row in range(3):
        parts = []
        for col in range(3):
            index = row * 3 + col
            parts.append("?" if index == missing_index else str(values[index]))
        rows.append(" | ".join(parts))
    answer = values[missing_index]
    return MathQuiz(
        question="\n".join(rows),
        answer=str(answer),
        explanation=f"\u4ece\u5de6\u5230\u53f3\u3001\u4ece\u4e0a\u5230\u4e0b\u8fde\u7eed\u9012\u589e\uff0c\u7f3a\u5931\u7684\u6570\u662f {answer}\u3002",
        kind="logic_grid",
    )


def _generate_emoji_calc_quiz(rng: random.Random) -> MathQuiz:
    symbols = rng.sample(["\U0001f7e1", "\U0001f535", "\U0001f7e2", "\U0001f7e3"], 2)
    a = rng.randint(2, 9)
    b = rng.randint(2, 9)
    answer = b * 2
    question = "\n".join(
        [
            f"{symbols[0]} + {symbols[0]} = {a * 2}",
            f"{symbols[0]} + {symbols[1]} = {a + b}",
            f"{symbols[1]} + {symbols[1]} = ?",
        ]
    )
    return MathQuiz(
        question=question,
        answer=str(answer),
        explanation=f"{symbols[0]}={a}\uff0c{symbols[1]}={b}\uff0c\u6240\u4ee5 {symbols[1]} + {symbols[1]} = {answer}\u3002",
        kind="emoji_calc",
    )


def _generate_square_pattern_quiz(rng: random.Random) -> MathQuiz:
    start = rng.randint(1, 3)
    seq = [(start + index) ** 2 for index in range(5)]
    visible = "  ".join(str(value) for value in seq[:4])
    return MathQuiz(
        question=f"\u627e\u89c4\u5f8b\uff1a{visible}  ?",
        answer=str(seq[4]),
        explanation=f"\u89c4\u5f8b\uff1a\u5e73\u65b9\u6570\uff0c\u6b63\u786e\u7b54\u6848\u662f {seq[4]}\u3002",
        kind="number_pattern",
    )


def is_packet_claim_text(packet: ActivePacket, text: str) -> bool:
    if packet.template_type == "math_quiz":
        answer = parse_math_quiz_answer(text)
        return bool(answer) and normalize_answer(answer) == normalize_answer(packet.passphrase)
    return packet.passphrase.strip() == text.strip()


def parse_math_quiz_answer(text: str) -> str | None:
    normalized = " ".join(text.strip().split())
    if re.fullmatch(r"-?\d+(?:\.\d+)?", normalized):
        return normalized
    match = re.match(r"^(?:\u7b54\u6848|\u7b54|answer)\s*[:\uff1a]?\s*(.+)$", normalized, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def normalize_answer(value: str) -> str:
    return " ".join(str(value).strip().split()).casefold()


def format_packet_announcement(packet: ActivePacket) -> str:
    return (
        f"\U0001f9e7 {html.escape(packet.creator_name)} \u53d1\u4e86\u4e00\u4e2a{html.escape(packet.template_name)}\n"
        f"\U0001f4b0 \u603b\u989d: {packet.total_amount} \uff5c \U0001f4e6 \u5171{packet.packet_count}\u4e2a\n"
        f"\U0001f194 \u7ea2\u5305ID: <code>{html.escape(packet.id)}</code>\n\n"
        "\u53d1\u9001\u4e0b\u65b9\u53e3\u4ee4\u9886\u53d6\uff1a\n"
        f"<code>{html.escape(packet.passphrase)}</code>"
    )


def format_math_quiz_announcement(packet: ActivePacket) -> str:
    return (
        f"\U0001f9ee {html.escape(packet.creator_name)} \u53d1\u8d77\u4e86\u4e00\u4e2a{html.escape(packet.template_name)}\n"
        f"\U0001f4b0 \u5956\u52b1: {packet.total_amount}\n"
        f"\U0001f194 \u7ea2\u5305ID: <code>{html.escape(packet.id)}</code>\n\n"
        "<b>\u9898\u76ee\uff1a</b>\n"
        f"<blockquote>{html.escape(packet.quiz_question)}</blockquote>\n"
        "\u76f4\u63a5\u56de\u590d\u6570\u5b57\u4f5c\u7b54\uff0c\u7b2c\u4e00\u4e2a\u7b54\u5bf9\u7684\u7528\u6237\u83b7\u5f97\u5956\u52b1\u3002"
    )


def format_math_quiz_completed(packet: ActivePacket, claim: PacketClaim) -> str:
    detail = packet.quiz_explanation or f"\u6b63\u786e\u7b54\u6848\uff1a{packet.passphrase}"
    return (
        f"\u2705 <b>{html.escape(packet.template_name)} [{html.escape(packet.id)}] \u5df2\u5b8c\u6210\u89e3\u7b54</b>\n"
        f"\U0001f4b0 \u5956\u52b1: {packet.total_amount} \uff5c \U0001f3c5 \u83b7\u5f97\u8005: {html.escape(claim.name)} +{claim.amount}\n\n"
        "<b>\u9898\u76ee\uff1a</b>\n"
        f"<blockquote>{html.escape(packet.quiz_question)}</blockquote>\n"
        f"\u6b63\u786e\u7b54\u6848\uff1a<code>{html.escape(packet.passphrase)}</code>\n"
        f"<blockquote expandable>{html.escape(detail)}</blockquote>"
    )


def format_packet_cancelled(packet: ActivePacket) -> str:
    claimed = len(packet.claims)
    remaining_count = max(packet.packet_count - claimed, 0)
    remaining_amount = sum(packet.allocations[claimed:])
    lines = [
        f"\u274c <b>{html.escape(packet.template_name)} [{html.escape(packet.id)}] \u5df2\u64a4\u9500</b>",
        f"\u53d1\u8d77\u4eba: {html.escape(packet.creator_name)}",
    ]
    if packet.template_type == "math_quiz":
        lines.extend(
            [
                f"\U0001f4b0 \u5956\u52b1: {packet.total_amount}",
                "<b>\u9898\u76ee\uff1a</b>",
                f"<blockquote>{html.escape(packet.quiz_question)}</blockquote>",
            ]
        )
    else:
        lines.extend(
            [
                f"\U0001f4b0 \u603b\u989d: {packet.total_amount} \uff5c \U0001f4e6 \u5171 {packet.packet_count} \u4e2a",
                f"\u5df2\u9886: {claimed}/{packet.packet_count} \uff5c \u672a\u9886: {remaining_count} \u4e2a \uff5c \u672a\u9886\u603b\u989d: {remaining_amount}",
            ]
        )
    return "\n".join(lines)


def format_packet_summary(packet: ActivePacket) -> str:
    lines = [
        f"\U0001f9e7 <b>{html.escape(packet.template_name)} [{html.escape(packet.id)}] \u5df2\u7ed3\u7b97!</b>",
        f"\U0001f4b0 \u603b\u989d: {packet.total_amount} \uff5c \U0001f4e6 \u5171 {packet.packet_count} \u4e2a",
        "\U0001f465 <b>\u9886\u53d6\u8be6\u60c5:</b>",
    ]
    best_amount = max((claim.amount for claim in packet.claims), default=0)
    detail_lines: list[str] = []
    for index, claim in enumerate(packet.claims, 1):
        suffix = " \U0001f31f \u624b\u6c14\u6700\u4f73" if claim.amount == best_amount and best_amount else ""
        detail_lines.append(f"{index}. {html.escape(claim.name)}: +{claim.amount}{suffix}")
    lines.append("<blockquote expandable>" + "\n".join(detail_lines) + "</blockquote>")
    return "\n".join(lines)

def format_packet_list(packets: list[ActivePacket]) -> str:
    if not packets:
        return "\u5f53\u524d\u6ca1\u6709\u672a\u9886\u5b8c\u7684\u7ea2\u5305\u3002"

    lines = ["\U0001f9e7 <b>\u672a\u9886\u5b8c\u7ea2\u5305\u5217\u8868</b>"]
    for index, packet in enumerate(packets, 1):
        claimed = len(packet.claims)
        remaining_count = max(packet.packet_count - claimed, 0)
        remaining_amount = sum(packet.allocations[claimed:])
        lines.extend(
            [
                "",
                f"{index}. <b>{html.escape(packet.template_name)}</b> <code>{html.escape(packet.id)}</code>",
                f"\u53d1\u8d77\u4eba: {html.escape(packet.creator_name)}",
                f"\u8fdb\u5ea6: {claimed}/{packet.packet_count} \uff5c \u5269\u4f59: {remaining_count} \u4e2a \uff5c \u5269\u4f59\u603b\u989d: {remaining_amount}",
            ]
        )
        if packet.template_type == "math_quiz":
            lines.append("\u4f5c\u7b54\u683c\u5f0f: <code>\u7b54\u6848 8</code>")
        else:
            lines.append(f"\u53e3\u4ee4: <code>{html.escape(packet.passphrase)}</code>")
    return "\n".join(lines)

async def reply_to_message(event: Any, text: str, reply_to: Any = None, parse_mode: str | None = None) -> Any:
    message = _event_message(event)
    client = getattr(event, "client", None)
    chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
    if client is not None and chat_id is not None and hasattr(client, "send_message"):
        kwargs = {}
        if reply_to is not None:
            kwargs["reply_to"] = reply_to
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        return await client.send_message(chat_id, text, **kwargs)
    target = message or event
    if hasattr(target, "reply") and reply_to is not None:
        return await target.reply(text)
    if hasattr(target, "respond"):
        return await target.respond(text)
    if hasattr(event, "respond"):
        return await event.respond(text)
    return None


async def safe_delete_message(message: Any, reason: str = "") -> bool:
    if message is None or not hasattr(message, "delete"):
        return False
    try:
        await message.delete()
        return True
    except Exception as exc:
        logger.warning("Failed to delete send red packet command message: reason=%s error=%s", reason, exc)
        return False


async def safe_edit_message_by_id(event: Any, message_id: str, text: str, parse_mode: str | None = None) -> bool:
    if not message_id or not str(message_id).isdigit():
        return False
    message = _event_message(event)
    client = getattr(event, "client", None)
    chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
    if client is None or chat_id is None or not hasattr(client, "edit_message"):
        return False
    kwargs = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    try:
        await client.edit_message(chat_id, int(message_id), text, **kwargs)
        return True
    except Exception as exc:
        logger.warning("Failed to edit send red packet message: message_id=%s error=%s", message_id, exc)
        return False


async def sender_display_name(event: Any) -> str:
    message = _event_message(event)
    for obj in (message, event):
        value = getattr(obj, "sender_name", "") or getattr(obj, "name", "")
        if value:
            return str(value)
    if message is not None and hasattr(message, "get_sender"):
        try:
            sender = await message.get_sender()
            name = _format_sender(sender)
            if name:
                return name
        except Exception:
            logger.exception("Failed to load send red packet sender")
    return _sender_id(message or event) or "\u7528\u6237"


def packet_from_dict(data: Any) -> ActivePacket | None:
    if not isinstance(data, dict):
        return None
    try:
        return ActivePacket(
            id=str(data["id"]),
            template_id=str(data.get("template_id") or "lucky-text"),
            template_name=str(data.get("template_name") or "\u62fc\u624b\u6c14\u7ea2\u5305"),
            template_type=str(data.get("template_type") or "lucky_text"),
            chat_id=str(data.get("chat_id") or ""),
            creator_id=str(data.get("creator_id") or ""),
            creator_name=str(data.get("creator_name") or "\u7528\u6237"),
            total_amount=int(data.get("total_amount") or 0),
            packet_count=int(data.get("packet_count") or 0),
            passphrase=str(data.get("passphrase") or ""),
            allocations=[int(item) for item in data.get("allocations", [])],
            claims=[
                PacketClaim(
                    sender_id=str(item.get("sender_id") or ""),
                    name=str(item.get("name") or "\u7528\u6237"),
                    amount=int(item.get("amount") or 0),
                    message_id=str(item.get("message_id") or ""),
                )
                for item in data.get("claims", [])
                if isinstance(item, dict)
            ],
            created_at=float(data.get("created_at") or 0),
            announcement_message_id=str(data.get("announcement_message_id") or ""),
            quiz_question=str(data.get("quiz_question") or ""),
            quiz_explanation=str(data.get("quiz_explanation") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def packet_to_dict(packet: ActivePacket) -> dict[str, Any]:
    return {
        "id": packet.id,
        "template_id": packet.template_id,
        "template_name": packet.template_name,
        "template_type": packet.template_type,
        "chat_id": packet.chat_id,
        "creator_id": packet.creator_id,
        "creator_name": packet.creator_name,
        "total_amount": packet.total_amount,
        "packet_count": packet.packet_count,
        "passphrase": packet.passphrase,
        "allocations": packet.allocations,
        "claims": [asdict(claim) for claim in packet.claims],
        "created_at": packet.created_at,
        "announcement_message_id": packet.announcement_message_id,
        "quiz_question": packet.quiz_question,
        "quiz_explanation": packet.quiz_explanation,
    }


def _format_sender(sender: Any) -> str:
    first = str(getattr(sender, "first_name", "") or "").strip()
    last = str(getattr(sender, "last_name", "") or "").strip()
    title = str(getattr(sender, "title", "") or "").strip()
    username = str(getattr(sender, "username", "") or "").strip()
    return " ".join(part for part in (first, last) if part) or title or username


def _event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def _chat_id(event: Any) -> str:
    message = _event_message(event)
    return str(getattr(message, "chat_id", getattr(event, "chat_id", "")))


def _message_text(message: Any) -> str:
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_outgoing(event: Any) -> bool:
    message = _event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


def _sender_id(message: Any) -> str:
    return str(getattr(message, "sender_id", "") or "")


def _preview(value: str, limit: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"
