from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.config import TelegramConfig
from telegram_bot.telegram.client import ProgrammaticMessageTracker, TelegramAdapter


def test_programmatic_tracker_covers_event_before_send_returns() -> None:
    tracker = ProgrammaticMessageTracker()
    token = tracker.begin("send_message", (-1001, "自动消息"), {})
    outgoing = SimpleNamespace(chat_id=-1001, id=21, raw_text="自动消息")

    assert tracker.is_programmatic(outgoing) is True

    tracker.finish(token, outgoing)

    assert tracker.is_programmatic(outgoing) is True


def test_pending_media_send_without_caption_waits_for_result_id() -> None:
    tracker = ProgrammaticMessageTracker()
    token = tracker.begin("send_file", (-1001, object()), {})

    manual_text = SimpleNamespace(chat_id=-1001, id=22, raw_text="本人消息", media=None)
    automatic_media = SimpleNamespace(chat_id=-1001, id=23, raw_text="", media=object())

    assert tracker.is_programmatic(manual_text) is False
    assert tracker.is_programmatic(automatic_media) is False

    tracker.finish(token, automatic_media)

    assert tracker.is_programmatic(automatic_media) is True


def test_pending_forward_does_not_overmatch_manual_forward() -> None:
    tracker = ProgrammaticMessageTracker()
    tracker.begin("forward_messages", (-1001, object()), {})
    manual_forward = SimpleNamespace(
        chat_id=-1001,
        id=24,
        raw_text="本人转发",
        fwd_from=object(),
    )

    assert tracker.is_programmatic(manual_forward) is False


def test_telegram_adapter_wraps_direct_client_sends_from_feature_modules(tmp_path: Path) -> None:
    class FakeTelegramClient:
        async def send_message(self, chat_id: int, text: str) -> object:
            return SimpleNamespace(chat_id=chat_id, id=31, raw_text=text)

    async def callback(event: object) -> None:
        return None

    adapter = TelegramAdapter(TelegramConfig(), tmp_path, callback)
    adapter.client = FakeTelegramClient()
    adapter._install_programmatic_message_tracking()

    sent = asyncio.run(adapter.client.send_message(-1001, "其他模块消息"))

    assert adapter.is_programmatic_message(sent) is True


def test_telegram_adapter_iterates_history_oldest_first_after_checkpoint(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeTelegramClient:
        async def iter_messages(self, entity: int, **kwargs: object):
            captured["entity"] = entity
            captured["kwargs"] = kwargs
            for message_id in (11, 12):
                yield SimpleNamespace(id=message_id)

    async def callback(event: object) -> None:
        return None

    async def collect() -> list[int]:
        adapter = TelegramAdapter(TelegramConfig(), tmp_path, callback)
        adapter.client = FakeTelegramClient()
        adapter.connected = True
        return [
            message.id
            async for message in adapter.iter_history_messages("-100123", min_id=10)
        ]

    assert asyncio.run(collect()) == [11, 12]
    assert captured["entity"] == -100123
    assert captured["kwargs"] == {"min_id": 10, "reverse": True}
