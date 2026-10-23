from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from telegram_bot.app import TelegramBotApplication
from telegram_bot.config import AppConfig, ChatHistoryConfig
from telegram_bot.jobs import ChatHistoryBackfillJob
from telegram_bot.persistence import ChatHistoryStore


def _event(
    text: str,
    *,
    chat_id: int = -1001234567890,
    message_id: int = 1,
    sender_id: int = 88,
    date: datetime | None = None,
    edit_date: datetime | None = None,
    media: object | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender_id=sender_id,
        raw_text=text,
        message=text,
        date=date or datetime(2026, 7, 28, tzinfo=timezone.utc),
        edit_date=edit_date,
        reply_to_msg_id=None,
        out=False,
        media=media,
    )
    return SimpleNamespace(message=message, chat_id=chat_id, sender_id=sender_id)


def test_chat_history_records_text_only_and_skips_media_without_caption(tmp_path: Path) -> None:
    database_path = tmp_path / "chat-history.sqlite3"
    store = ChatHistoryStore(ChatHistoryConfig(database_path=str(database_path)), tmp_path)

    assert store.record_event(_event("一条普通消息", message_id=1)) is True
    assert store.record_event(_event("", message_id=2, media=object())) is False
    assert store.record_event(_event("图片说明文字", message_id=3, media=object())) is True

    messages = store.get_user_messages(-1001234567890, 88, 20)
    assert [message.message_id for message in messages] == [1, 3]
    assert [message.text for message in messages] == ["一条普通消息", "图片说明文字"]
    store.close()

    with closing(sqlite3.connect(database_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")}
        count = connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    assert count == 2
    assert not ({"blob", "media", "file", "file_path", "binary"} & columns)


def test_chat_history_edit_upserts_and_empty_edit_removes_text(tmp_path: Path) -> None:
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    sent_at = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    store.record_event(_event("初稿", message_id=7, date=sent_at))
    store.record_event(
        _event(
            "修订稿",
            message_id=7,
            date=sent_at,
            edit_date=sent_at + timedelta(minutes=1),
        )
    )

    messages = store.get_user_messages(-1001234567890, 88, 20)
    assert len(messages) == 1
    assert messages[0].text == "修订稿"
    assert messages[0].edited_at == sent_at + timedelta(minutes=1)

    store.record_event(_event("", message_id=7, date=sent_at, edit_date=sent_at + timedelta(minutes=2)))
    assert store.get_user_messages(-1001234567890, 88, 20) == []
    store.close()


def test_chat_history_queries_by_chat_sender_and_recent_limit(tmp_path: Path) -> None:
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    base = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    for message_id in range(1, 6):
        store.record_event(
            _event(
                f"消息 {message_id}",
                message_id=message_id,
                date=base + timedelta(minutes=message_id),
            )
        )
    store.record_event(_event("其他发送者", message_id=6, sender_id=99))
    store.record_event(_event("其他群", chat_id=-1009999999999, message_id=7))

    messages = store.get_user_messages(-1001234567890, 88, 3)

    assert [message.message_id for message in messages] == [3, 4, 5]
    assert [message.text for message in messages] == ["消息 3", "消息 4", "消息 5"]
    store.close()


def test_chat_history_batch_write_and_unlimited_user_query(tmp_path: Path) -> None:
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    events = [_event(f"消息 {message_id}", message_id=message_id) for message_id in range(1, 5202)]

    assert store.record_events(events) == 5201
    messages = store.get_user_messages(-1001234567890, 88, None)

    assert len(messages) == 5201
    assert messages[0].message_id == 1
    assert messages[-1].message_id == 5201
    store.close()


def test_chat_history_queries_one_sender_across_chats_without_message_id_collisions(tmp_path: Path) -> None:
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    store.record_event(_event("群一", chat_id=-1001, message_id=7, sender_id=88))
    store.record_event(_event("群二", chat_id=-1002, message_id=7, sender_id=88))
    store.record_event(_event("其他用户", chat_id=-1002, message_id=8, sender_id=99))

    messages = store.get_user_messages_across_chats([-1001, -1002], 88)

    assert [(item.chat_id, item.message_id, item.text) for item in messages] == [
        (-1002, 7, "群二"),
        (-1001, 7, "群一"),
    ]
    store.close()


def test_history_backfill_resumes_from_sqlite_checkpoint(tmp_path: Path) -> None:
    chat_id = "-1001234567890"
    history = [
        _event("第一条", message_id=1).message,
        _event("", message_id=2, media=object()).message,
        _event("第三条", message_id=3).message,
    ]

    class FakeTelegram:
        connected = True

        def __init__(self) -> None:
            self.min_ids: list[int] = []

        async def iter_history_messages(self, target: str, *, min_id: int = 0):
            assert target == chat_id
            self.min_ids.append(min_id)
            for message in history:
                if message.id > min_id:
                    yield message

    async def run_backfills() -> tuple[FakeTelegram, ChatHistoryStore]:
        telegram = FakeTelegram()
        config = ChatHistoryConfig(
            database_path=str(tmp_path / "chat-history.sqlite3"),
            backfill_enabled=True,
            backfill_batch_size=2,
        )
        store = ChatHistoryStore(config, tmp_path)
        telegram_config = AppConfig().telegram
        telegram_config.monitored_groups = [chat_id]
        job = ChatHistoryBackfillJob(config, telegram_config, telegram, store)

        await job.start()
        assert job._task is not None
        await job._task

        state = store.get_backfill_state(chat_id)
        assert state is not None
        assert state.is_complete is True
        assert state.last_message_id == 3
        assert state.scanned_messages == 3
        assert state.stored_messages == 2

        history.append(_event("第四条", message_id=4).message)
        await job.start()
        assert job._task is not None
        await job._task
        return telegram, store

    telegram, store = asyncio.run(run_backfills())

    assert telegram.min_ids == [0, 3]
    assert [item.message_id for item in store.get_user_messages(chat_id, 88, None)] == [1, 3, 4]
    state = store.get_backfill_state(chat_id)
    assert state is not None
    assert state.is_complete is True
    assert state.last_message_id == 4
    store.close()


def test_application_archives_monitored_event_before_module_dispatch(tmp_path: Path) -> None:
    config = AppConfig()
    config.chat_history.database_path = str(tmp_path / "chat-history.sqlite3")
    app = TelegramBotApplication(config, tmp_path / "config.json")
    event = _event("需要长期保存的聊天", message_id=42)

    asyncio.run(app._on_telegram_message(event))

    messages = app.chat_history.get_user_messages(-1001234567890, 88, 10)
    assert [message.message_id for message in messages] == [42]
    assert messages[0].text == "需要长期保存的聊天"
    app.chat_history.close()


def test_disabled_chat_history_does_not_create_database(tmp_path: Path) -> None:
    database_path = tmp_path / "chat-history.sqlite3"
    store = ChatHistoryStore(
        ChatHistoryConfig(enabled=False, database_path=str(database_path)),
        tmp_path,
    )

    assert store.record_event(_event("不应保存", message_id=1)) is False
    assert store.get_user_messages(-1001234567890, 88, 10) == []
    store.close()

    assert database_path.exists() is False


def test_close_prevents_waiting_writer_from_reopening_database(tmp_path: Path) -> None:
    database_path = tmp_path / "chat-history.sqlite3"
    store = ChatHistoryStore(ChatHistoryConfig(database_path=str(database_path)), tmp_path)
    store.record_event(_event("关闭前", message_id=1))
    text_read = threading.Event()

    class WaitingMessage:
        id = 2
        chat_id = -1001234567890
        sender_id = 88
        date = datetime(2026, 7, 28, tzinfo=timezone.utc)
        edit_date = None
        reply_to_msg_id = None
        out = False

        @property
        def raw_text(self) -> str:
            text_read.set()
            return "关闭后不应写入"

    event = SimpleNamespace(message=WaitingMessage(), chat_id=-1001234567890, sender_id=88)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with store._lock:
            pending_write = executor.submit(store.record_event, event)
            assert text_read.wait(timeout=1)
            store.close()
        assert pending_write.result(timeout=1) is False

    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute("SELECT message_id, text FROM chat_messages ORDER BY message_id").fetchall()
    assert rows == [(1, "关闭前")]


def test_archive_initialization_failure_does_not_block_module_dispatch(tmp_path: Path) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("占位文件", encoding="utf-8")
    config = AppConfig()
    config.chat_history.database_path = str(blocked_parent / "chat-history.sqlite3")
    app = TelegramBotApplication(config, tmp_path / "config.json")
    dispatched: list[object] = []

    async def dispatch_message(event: object) -> list[object]:
        dispatched.append(event)
        return []

    app.modules.dispatch_message = dispatch_message  # type: ignore[method-assign]
    event = _event("归档失败也要继续分发", message_id=9)

    with patch("telegram_bot.app.logger.exception"):
        asyncio.run(app._on_telegram_message(event))

    assert dispatched == [event]
    assert app.metrics.messages_seen == 1
    app.chat_history.close()
