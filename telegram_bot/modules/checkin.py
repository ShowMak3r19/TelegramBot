from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as datetime_time
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot.config import CheckinConfig, CheckinTaskConfig
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)
Sender = Callable[[str, str], Awaitable[None]]

_CRON_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("分钟", 0, 59),
    ("小时", 0, 23),
    ("日期", 1, 31),
    ("月份", 1, 12),
    ("星期", 0, 7),
)
_WEEKDAY_NAMES = {
    0: "周日",
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
}


@dataclass(frozen=True, slots=True)
class ParsedCron:
    source: str
    minute: frozenset[int]
    hour: frozenset[int]
    day: frozenset[int]
    month: frozenset[int]
    weekday: frozenset[int]
    day_wildcard: bool
    weekday_wildcard: bool


class CheckinModule:
    def __init__(
        self,
        card: ModuleCard,
        config: CheckinConfig,
        project_root: Path | None = None,
        sender: Sender | None = None,
    ) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.sender = sender
        self.state_path = self._resolve_path(self.config.state_store)
        self.sent_keys = self._load_state()
        self._task: asyncio.Task[None] | None = None
        self._sync_card_config()

    def set_sender(self, sender: Sender) -> None:
        self.sender = sender

    async def start(self) -> None:
        self.card.status = "running"
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop(), name="checkin-scheduler")
        logger.info(
            "Checkin scheduler started: tasks=%s active=%s",
            len(self.config.tasks),
            self._enabled_task_count(),
        )

    async def stop(self) -> None:
        self.card.status = "stopped"
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Checkin scheduler stopped")

    async def handle_message(self, message: Any) -> HandlerResult:
        return HandlerResult.ignored(self.card.id)

    def update_config(self, values: dict[str, Any]) -> None:
        new_tasks = self.config.tasks
        tasks = values.get("tasks")
        if isinstance(tasks, list):
            new_tasks = [
                _task_from_dict(item) for item in tasks if isinstance(item, dict)
            ]

        new_poll_interval = self.config.poll_interval_seconds
        if "poll_interval_seconds" in values:
            new_poll_interval = max(
                1.0, min(float(values.get("poll_interval_seconds") or 10.0), 300.0)
            )

        new_state_store = self.config.state_store
        new_state_path = self.state_path
        new_sent_keys = self.sent_keys
        if "state_store" in values:
            new_state_store = str(
                values.get("state_store") or "runtime/data/checkin_state.json"
            )
            new_state_path = self._resolve_path(new_state_store)
            new_sent_keys = self._load_state(new_state_path)

        self.config.tasks = new_tasks
        self.config.poll_interval_seconds = new_poll_interval
        self.config.state_store = new_state_store
        if "state_store" in values:
            self.state_path = new_state_path
            self.sent_keys = new_sent_keys
        self._sync_card_config()
        logger.info(
            "Checkin config updated: tasks=%s active=%s",
            len(self.config.tasks),
            self._enabled_task_count(),
        )

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick(datetime.now())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Checkin scheduler tick failed")
            await asyncio.sleep(
                max(1.0, float(self.config.poll_interval_seconds or 10.0))
            )

    async def _tick(self, now: datetime) -> None:
        if self.sender is None:
            logger.debug("Checkin scheduler waiting for Telegram sender")
            return
        for task in self.config.tasks:
            if not task.enabled or not task.target.strip() or not task.message.strip():
                continue
            schedule = task_cron(task)
            due_time = due_checkin_cron(schedule, now)
            if due_time is None:
                continue
            key = build_sent_key(task.id, now, due_time)
            if key in self.sent_keys:
                continue
            await self.sender(task.target.strip(), task.message.strip())
            self.sent_keys[key] = time.time()
            self._save_state(now)
            logger.info(
                "Checkin sent: task=%s target=%s time=%s cron=%s",
                task.name or task.id,
                task.target,
                due_time,
                schedule.replace("\n", "; "),
            )

    def _sync_card_config(self) -> None:
        self.card.config = {
            "tasks": [_task_snapshot(task) for task in self.config.tasks],
            "task_count": len(self.config.tasks),
            "enabled_task_count": self._enabled_task_count(),
            "poll_interval_seconds": self.config.poll_interval_seconds,
            "state_store": self.config.state_store,
        }

    def _enabled_task_count(self) -> int:
        return sum(1 for task in self.config.tasks if task.enabled)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        root = self.project_root or Path.cwd()
        return root / path

    def _load_state(self, path: Path | None = None) -> dict[str, float]:
        state_path = path or self.state_path
        if not state_path.exists():
            return {}
        try:
            with state_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load checkin state, starting empty")
            return {}
        sent = data.get("sent", {}) if isinstance(data, dict) else {}
        if not isinstance(sent, dict):
            return {}
        return {
            str(key): float(value)
            for key, value in sent.items()
            if _as_float(value) is not None
        }

    def _save_state(self, now: datetime | None = None) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        today_prefix = (now or datetime.now()).strftime("%Y-%m-%d")
        self.sent_keys = {
            key: value
            for key, value in self.sent_keys.items()
            if key.startswith(today_prefix)
        }
        self.state_path.write_text(
            json.dumps(
                {"version": 1, "sent": self.sent_keys}, indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )


def due_checkin_time(times: list[str], now: datetime) -> str | None:
    for value in times:
        parsed = parse_schedule_time(value)
        if parsed is None:
            continue
        due = now.replace(
            hour=parsed.hour, minute=parsed.minute, second=parsed.second, microsecond=0
        )
        delta = (now - due).total_seconds()
        if 0 <= delta < 60:
            return parsed.strftime("%H:%M:%S")
    return None


def due_checkin_cron(schedule: str, now: datetime) -> str | None:
    for expression in split_cron_expressions(schedule):
        try:
            if _parsed_cron_matches(_parse_cron(expression), now):
                return now.strftime("%H:%M:00")
        except ValueError:
            # Invalid persisted entries are ignored so one bad task cannot stop
            # the scheduler. Admin updates validate before replacing the config.
            continue
    return None


def cron_matches(expression: str, now: datetime) -> bool:
    return _parsed_cron_matches(_parse_cron(expression), now)


def validate_cron_schedule(schedule: str) -> str:
    expressions = split_cron_expressions(schedule)
    if not expressions:
        raise ValueError("Cron 表达式不能为空")
    normalized: list[str] = []
    for index, expression in enumerate(expressions, start=1):
        try:
            normalized.append(_parse_cron(expression).source)
        except ValueError as exc:
            prefix = f"第 {index} 行 " if len(expressions) > 1 else ""
            raise ValueError(f"{prefix}{exc}") from exc
    return "\n".join(normalized)


def describe_cron_schedule(schedule: str) -> str:
    normalized = validate_cron_schedule(schedule)
    return "；".join(
        describe_cron_expression(item) for item in split_cron_expressions(normalized)
    )


def describe_cron_expression(expression: str) -> str:
    parsed = _parse_cron(expression)
    minute_text, hour_text, day_text, month_text, weekday_text = parsed.source.split()

    minute_step = _wildcard_step(minute_text)
    if minute_step and hour_text == day_text == month_text == weekday_text == "*":
        return f"每隔 {minute_step} 分钟发送一次"
    if parsed.source == "* * * * *":
        return "每分钟发送一次"

    times = _fixed_times(parsed)
    time_description = "、".join(times) if times else ""

    day_step = _wildcard_step(day_text)
    if day_step and month_text == "*" and weekday_text == "*" and time_description:
        return f"每月从 1 日开始每隔 {day_step} 天，于 {time_description} 发送"

    if (
        day_text == "*"
        and month_text == "*"
        and weekday_text != "*"
        and time_description
    ):
        weekdays = "、".join(
            _WEEKDAY_NAMES[value] for value in _ordered_weekdays(parsed.weekday)
        )
        return f"每{weekdays} {time_description} 发送"

    if day_text == month_text == weekday_text == "*" and time_description:
        hour_step = _wildcard_step(hour_text)
        if hour_step and len(parsed.minute) == 1:
            minute = next(iter(parsed.minute))
            return f"每隔 {hour_step} 小时的第 {minute:02d} 分钟发送一次"
        return f"每天 {time_description} 发送"

    if (
        day_text == month_text == weekday_text == "*"
        and hour_text == "*"
        and len(parsed.minute) == 1
    ):
        minute = next(iter(parsed.minute))
        return f"每小时第 {minute:02d} 分钟发送"

    if (
        month_text == "*"
        and weekday_text == "*"
        and time_description
        and len(parsed.day) <= 8
    ):
        days = "、".join(f"{value} 日" for value in sorted(parsed.day))
        return f"每月 {days} {time_description} 发送"

    if (
        weekday_text == "*"
        and time_description
        and len(parsed.month) <= 4
        and len(parsed.day) <= 4
    ):
        months = "、".join(f"{value} 月" for value in sorted(parsed.month))
        days = "、".join(f"{value} 日" for value in sorted(parsed.day))
        return f"每年 {months} {days} {time_description} 发送"

    return f"按 Cron「{parsed.source}」执行"


def split_cron_expressions(schedule: str) -> list[str]:
    return [line.strip() for line in str(schedule or "").splitlines() if line.strip()]


def cron_from_daily_times(times: list[str]) -> str:
    expressions: list[str] = []
    for value in times:
        parsed = parse_schedule_time(value)
        if parsed is None:
            continue
        expression = f"{parsed.minute} {parsed.hour} * * *"
        if expression not in expressions:
            expressions.append(expression)
    return "\n".join(expressions)


def task_cron(task: CheckinTaskConfig) -> str:
    return str(task.cron or "").strip() or cron_from_daily_times(task.times)


def _task_snapshot(task: CheckinTaskConfig) -> dict[str, Any]:
    data = asdict(task)
    schedule = task_cron(task)
    data["cron"] = schedule
    try:
        data["schedule_description"] = describe_cron_schedule(schedule)
        data["schedule_valid"] = True
    except ValueError as exc:
        data["schedule_description"] = str(exc)
        data["schedule_valid"] = False
    return data


def _parse_cron(expression: str) -> ParsedCron:
    source = " ".join(str(expression or "").strip().split())
    fields = source.split()
    if len(fields) != 5:
        raise ValueError("Cron 表达式必须包含 5 个字段（分 时 日 月 周）")

    values: list[frozenset[int]] = []
    for text, (label, minimum, maximum) in zip(fields, _CRON_FIELDS):
        parsed = _parse_cron_field(text, label, minimum, maximum)
        if label == "星期":
            parsed = {0 if value == 7 else value for value in parsed}
        values.append(frozenset(parsed))

    return ParsedCron(
        source=source,
        minute=values[0],
        hour=values[1],
        day=values[2],
        month=values[3],
        weekday=values[4],
        day_wildcard=fields[2] == "*",
        weekday_wildcard=fields[4] == "*",
    )


def _parse_cron_field(text: str, label: str, minimum: int, maximum: int) -> set[int]:
    if not text or any(character.isspace() for character in text):
        raise ValueError(f"Cron 的{label}字段为空或包含空格")
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise ValueError(f"Cron 的{label}字段包含空项")
        if part.count("/") > 1:
            raise ValueError(f"Cron 的{label}字段步长格式无效：{part}")
        base, separator, step_text = part.partition("/")
        step = 1
        if separator:
            step = _cron_int(step_text, label, "步长")
            if step <= 0:
                raise ValueError(f"Cron 的{label}字段步长必须大于 0")

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            if base.count("-") != 1:
                raise ValueError(f"Cron 的{label}字段范围无效：{base}")
            start_text, end_text = base.split("-", 1)
            start = _cron_int(start_text, label, "范围起点")
            end = _cron_int(end_text, label, "范围终点")
        else:
            start = _cron_int(base, label, "值")
            end = maximum if separator else start

        if not minimum <= start <= maximum or not minimum <= end <= maximum:
            raise ValueError(
                f"Cron 的{label}字段必须在 {minimum}–{maximum} 之间：{part}"
            )
        if start > end:
            raise ValueError(f"Cron 的{label}字段范围起点不能大于终点：{part}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"Cron 的{label}字段没有可执行值")
    return values


def _cron_int(value: str, label: str, kind: str) -> int:
    if not re.fullmatch(r"\d+", value or ""):
        raise ValueError(f"Cron 的{label}字段{kind}必须是整数：{value or '空'}")
    return int(value)


def _parsed_cron_matches(parsed: ParsedCron, now: datetime) -> bool:
    if (
        now.minute not in parsed.minute
        or now.hour not in parsed.hour
        or now.month not in parsed.month
    ):
        return False
    day_matches = now.day in parsed.day
    cron_weekday = (now.weekday() + 1) % 7
    weekday_matches = cron_weekday in parsed.weekday
    if parsed.day_wildcard:
        return weekday_matches
    if parsed.weekday_wildcard:
        return day_matches
    # Standard cron treats restricted day-of-month and day-of-week fields as OR.
    return day_matches or weekday_matches


def _wildcard_step(value: str) -> int | None:
    match = re.fullmatch(r"\*/(\d+)", value)
    return int(match.group(1)) if match else None


def _fixed_times(parsed: ParsedCron) -> list[str]:
    if len(parsed.hour) * len(parsed.minute) > 12:
        return []
    return [
        f"{hour:02d}:{minute:02d}"
        for hour in sorted(parsed.hour)
        for minute in sorted(parsed.minute)
    ]


def _ordered_weekdays(values: frozenset[int]) -> list[int]:
    return [value for value in (1, 2, 3, 4, 5, 6, 0) if value in values]


def parse_schedule_time(value: str) -> datetime_time | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def build_sent_key(task_id: str, now: datetime, due_time: str) -> str:
    return f"{now:%Y-%m-%d}|{task_id}|{due_time}"


def _task_from_dict(data: dict[str, Any]) -> CheckinTaskConfig:
    legacy_times = _clean_list(data.get("times"))
    schedule = str(data.get("cron") or "").strip() or cron_from_daily_times(
        legacy_times
    )
    schedule = validate_cron_schedule(schedule)
    return CheckinTaskConfig(
        id=str(data.get("id") or "").strip() or f"checkin_{int(time.time() * 1000)}",
        name=str(data.get("name") or "").strip(),
        enabled=bool(data.get("enabled", True)),
        target=str(data.get("target") or "").strip(),
        target_title=str(data.get("target_title") or "").strip(),
        cron=schedule,
        times=legacy_times,
        message=str(data.get("message") or "").strip(),
    )


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
