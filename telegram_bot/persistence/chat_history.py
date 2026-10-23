from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram_bot.config import ChatHistoryConfig

logger = logging.getLogger(__name__)

_UPSERT_MESSAGE_SQL = """
INSERT INTO chat_messages (
    chat_id,
    message_id,
    sender_id,
    sent_at,
    edited_at,
    text,
    is_outgoing,
    reply_to_message_id,
    first_seen_at,
    last_seen_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(chat_id, message_id) DO UPDATE SET
    sender_id = COALESCE(excluded.sender_id, chat_messages.sender_id),
    sent_at = COALESCE(excluded.sent_at, chat_messages.sent_at),
    edited_at = COALESCE(excluded.edited_at, chat_messages.edited_at),
    text = excluded.text,
    is_outgoing = excluded.is_outgoing,
    reply_to_message_id = COALESCE(excluded.reply_to_message_id, chat_messages.reply_to_message_id),
    last_seen_at = excluded.last_seen_at
"""


@dataclass(frozen=True)
class StoredChatMessage:
    chat_id: int
    message_id: int
    sender_id: int | None
    sent_at: datetime | None
    edited_at: datetime | None
    text: str
    is_outgoing: bool
    reply_to_message_id: int | None


@dataclass(frozen=True)
class ChatHistoryBackfillState:
    chat_id: int
    last_message_id: int
    is_complete: bool
    scanned_messages: int
    stored_messages: int
    updated_at: datetime | None
    completed_at: datetime | None
    last_error: str


class ChatHistoryStore:
    """SQLite-backed text-only archive for monitored Telegram messages."""

    def __init__(self, config: ChatHistoryConfig, project_root: Path) -> None:
        self.config = config
        configured_path = Path(config.database_path)
        self.path = configured_path if configured_path.is_absolute() else project_root / configured_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._closed = False

    def record_event(self, event: Any) -> bool:
        if not self.config.enabled:
            return False

        normalized = self._normalize_event(event)
        if normalized is None:
            return False
        chat_id, message_id, values = normalized
        if values is None:
            self.delete_message(chat_id, message_id)
            return False

        with self._lock:
            if self._closed:
                return False
            self._connect().execute(_UPSERT_MESSAGE_SQL, values)
        return True

    def record_events(self, events: list[Any], *, fallback_chat_id: Any = None) -> int:
        """Persist a Telegram history page in one transaction and return text rows stored."""
        if not self.config.enabled or not events:
            return 0

        upserts: list[tuple[Any, ...]] = []
        deletions: list[tuple[int, int]] = []
        for event in events:
            normalized = self._normalize_event(event, fallback_chat_id=fallback_chat_id)
            if normalized is None:
                continue
            chat_id, message_id, values = normalized
            if values is None:
                deletions.append((chat_id, message_id))
            else:
                upserts.append(values)

        with self._lock:
            if self._closed:
                return 0
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            try:
                if deletions:
                    connection.executemany(
                        "DELETE FROM chat_messages WHERE chat_id = ? AND message_id = ?",
                        deletions,
                    )
                if upserts:
                    connection.executemany(_UPSERT_MESSAGE_SQL, upserts)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return len(upserts)

    def _normalize_event(
        self,
        event: Any,
        *,
        fallback_chat_id: Any = None,
    ) -> tuple[int, int, tuple[Any, ...] | None] | None:
        nested_message = getattr(event, "message", None)
        message = nested_message if getattr(nested_message, "id", None) is not None else event
        chat_id = _as_int(
            getattr(event, "chat_id", getattr(message, "chat_id", fallback_chat_id))
            or fallback_chat_id
        )
        message_id = _as_int(getattr(message, "id", None))
        if chat_id is None or message_id is None:
            return None

        text = str(getattr(message, "raw_text", getattr(message, "message", "")) or "").strip()
        if not text:
            return chat_id, message_id, None
        text = text[: self.config.max_text_length]

        sender_id = _as_int(getattr(message, "sender_id", getattr(event, "sender_id", None)))
        sent_at = _as_timestamp(getattr(message, "date", None))
        edited_at = _as_timestamp(getattr(message, "edit_date", None))
        reply_to_message_id = _as_int(getattr(message, "reply_to_msg_id", None))
        now = time.time()
        return (
            chat_id,
            message_id,
            (
                chat_id,
                message_id,
                sender_id,
                sent_at,
                edited_at,
                text,
                int(bool(getattr(message, "out", False))),
                reply_to_message_id,
                now,
                now,
            ),
        )

    def delete_message(self, chat_id: int, message_id: int) -> None:
        if not self.config.enabled or not self.path.exists():
            return
        with self._lock:
            if self._closed:
                return
            self._connect().execute(
                "DELETE FROM chat_messages WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            )

    def get_user_messages(
        self,
        chat_id: Any,
        sender_id: Any,
        limit: int | None = None,
    ) -> list[StoredChatMessage]:
        if not self.config.enabled or not self.path.exists():
            return []
        numeric_chat_id = _as_int(chat_id)
        numeric_sender_id = _as_int(sender_id)
        if numeric_chat_id is None or numeric_sender_id is None:
            return []
        with self._lock:
            if self._closed:
                return []
            query = """
                SELECT
                    chat_id,
                    message_id,
                    sender_id,
                    sent_at,
                    edited_at,
                    text,
                    is_outgoing,
                    reply_to_message_id
                FROM chat_messages
                WHERE chat_id = ? AND sender_id = ?
                ORDER BY COALESCE(sent_at, 0) DESC, message_id DESC
            """
            parameters: tuple[Any, ...] = (numeric_chat_id, numeric_sender_id)
            if limit is not None:
                query += " LIMIT ?"
                parameters += (max(1, int(limit)),)
            rows = self._connect().execute(query, parameters).fetchall()

        messages = [
            StoredChatMessage(
                chat_id=int(row[0]),
                message_id=int(row[1]),
                sender_id=int(row[2]) if row[2] is not None else None,
                sent_at=_from_timestamp(row[3]),
                edited_at=_from_timestamp(row[4]),
                text=str(row[5]),
                is_outgoing=bool(row[6]),
                reply_to_message_id=int(row[7]) if row[7] is not None else None,
            )
            for row in rows
        ]
        messages.reverse()
        return messages

    def get_user_messages_across_chats(
        self,
        chat_ids: list[Any],
        sender_id: Any,
    ) -> list[StoredChatMessage]:
        """Return one user's complete text history across the selected chats."""
        if not self.config.enabled or not self.path.exists():
            return []
        numeric_chat_ids = list(
            dict.fromkeys(
                parsed
                for value in chat_ids
                if (parsed := _as_int(value)) is not None
            )
        )
        numeric_sender_id = _as_int(sender_id)
        if not numeric_chat_ids or numeric_sender_id is None:
            return []
        placeholders = ",".join("?" for _ in numeric_chat_ids)
        query = f"""
            SELECT
                chat_id,
                message_id,
                sender_id,
                sent_at,
                edited_at,
                text,
                is_outgoing,
                reply_to_message_id
            FROM chat_messages
            WHERE chat_id IN ({placeholders}) AND sender_id = ?
            ORDER BY COALESCE(sent_at, 0) ASC, chat_id ASC, message_id ASC
        """
        with self._lock:
            if self._closed:
                return []
            rows = self._connect().execute(
                query,
                (*numeric_chat_ids, numeric_sender_id),
            ).fetchall()
        return [
            StoredChatMessage(
                chat_id=int(row[0]),
                message_id=int(row[1]),
                sender_id=int(row[2]) if row[2] is not None else None,
                sent_at=_from_timestamp(row[3]),
                edited_at=_from_timestamp(row[4]),
                text=str(row[5]),
                is_outgoing=bool(row[6]),
                reply_to_message_id=int(row[7]) if row[7] is not None else None,
            )
            for row in rows
        ]

    def mark_backfill_started(self, chat_id: Any) -> None:
        numeric_chat_id = _required_int(chat_id, "chat_id")
        now = time.time()
        with self._lock:
            if self._closed:
                return
            self._connect().execute(
                """
                INSERT INTO chat_history_backfill (
                    chat_id, last_message_id, is_complete, scanned_messages,
                    stored_messages, started_at, updated_at, completed_at, last_error
                ) VALUES (?, 0, 0, 0, 0, ?, ?, NULL, '')
                ON CONFLICT(chat_id) DO UPDATE SET
                    is_complete = 0,
                    started_at = excluded.started_at,
                    updated_at = excluded.updated_at,
                    completed_at = NULL,
                    last_error = ''
                """,
                (numeric_chat_id, now, now),
            )

    def update_backfill_progress(
        self,
        chat_id: Any,
        last_message_id: Any,
        *,
        scanned_messages: int,
        stored_messages: int,
    ) -> None:
        numeric_chat_id = _required_int(chat_id, "chat_id")
        numeric_message_id = max(0, _required_int(last_message_id, "last_message_id"))
        now = time.time()
        with self._lock:
            if self._closed:
                return
            self._connect().execute(
                """
                INSERT INTO chat_history_backfill (
                    chat_id, last_message_id, is_complete, scanned_messages,
                    stored_messages, started_at, updated_at, completed_at, last_error
                ) VALUES (?, ?, 0, ?, ?, ?, ?, NULL, '')
                ON CONFLICT(chat_id) DO UPDATE SET
                    last_message_id = MAX(chat_history_backfill.last_message_id, excluded.last_message_id),
                    is_complete = 0,
                    scanned_messages = chat_history_backfill.scanned_messages + excluded.scanned_messages,
                    stored_messages = chat_history_backfill.stored_messages + excluded.stored_messages,
                    updated_at = excluded.updated_at,
                    completed_at = NULL,
                    last_error = ''
                """,
                (
                    numeric_chat_id,
                    numeric_message_id,
                    max(0, int(scanned_messages)),
                    max(0, int(stored_messages)),
                    now,
                    now,
                ),
            )

    def mark_backfill_complete(self, chat_id: Any, last_message_id: Any) -> None:
        numeric_chat_id = _required_int(chat_id, "chat_id")
        numeric_message_id = max(0, _required_int(last_message_id, "last_message_id"))
        now = time.time()
        with self._lock:
            if self._closed:
                return
            self._connect().execute(
                """
                INSERT INTO chat_history_backfill (
                    chat_id, last_message_id, is_complete, scanned_messages,
                    stored_messages, started_at, updated_at, completed_at, last_error
                ) VALUES (?, ?, 1, 0, 0, ?, ?, ?, '')
                ON CONFLICT(chat_id) DO UPDATE SET
                    last_message_id = MAX(chat_history_backfill.last_message_id, excluded.last_message_id),
                    is_complete = 1,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    last_error = ''
                """,
                (numeric_chat_id, numeric_message_id, now, now, now),
            )

    def mark_backfill_failed(self, chat_id: Any, error: str) -> None:
        numeric_chat_id = _required_int(chat_id, "chat_id")
        now = time.time()
        with self._lock:
            if self._closed:
                return
            self._connect().execute(
                """
                INSERT INTO chat_history_backfill (
                    chat_id, last_message_id, is_complete, scanned_messages,
                    stored_messages, started_at, updated_at, completed_at, last_error
                ) VALUES (?, 0, 0, 0, 0, ?, ?, NULL, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    is_complete = 0,
                    updated_at = excluded.updated_at,
                    completed_at = NULL,
                    last_error = excluded.last_error
                """,
                (numeric_chat_id, now, now, str(error or "")[:1000]),
            )

    def get_backfill_state(self, chat_id: Any) -> ChatHistoryBackfillState | None:
        if not self.config.enabled or not self.path.exists():
            return None
        numeric_chat_id = _as_int(chat_id)
        if numeric_chat_id is None:
            return None
        with self._lock:
            if self._closed:
                return None
            row = self._connect().execute(
                """
                SELECT chat_id, last_message_id, is_complete, scanned_messages,
                       stored_messages, updated_at, completed_at, last_error
                FROM chat_history_backfill
                WHERE chat_id = ?
                """,
                (numeric_chat_id,),
            ).fetchone()
        if row is None:
            return None
        return ChatHistoryBackfillState(
            chat_id=int(row[0]),
            last_message_id=int(row[1]),
            is_complete=bool(row[2]),
            scanned_messages=int(row[3]),
            stored_messages=int(row[4]),
            updated_at=_from_timestamp(row[5]),
            completed_at=_from_timestamp(row[6]),
            last_error=str(row[7] or ""),
        )

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Chat history store is closed")
        if self._connection is not None:
            return self._connection

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None, check_same_thread=False)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sent_at REAL,
                    edited_at REAL,
                    text TEXT NOT NULL,
                    is_outgoing INTEGER NOT NULL DEFAULT 0,
                    reply_to_message_id INTEGER,
                    first_seen_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, message_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_time
                ON chat_messages (chat_id, sender_id, sent_at DESC, message_id DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history_backfill (
                    chat_id INTEGER PRIMARY KEY,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    is_complete INTEGER NOT NULL DEFAULT 0,
                    scanned_messages INTEGER NOT NULL DEFAULT 0,
                    stored_messages INTEGER NOT NULL DEFAULT 0,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    last_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
        except Exception:
            connection.close()
            raise
        self._connection = connection
        logger.info("Chat history database ready: path=%s", self.path)
        return connection


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _required_int(value: Any, name: str) -> int:
    parsed = _as_int(value)
    if parsed is None:
        raise ValueError(f"{name} must be an integer")
    return parsed


def _as_timestamp(value: Any) -> float | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _from_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
