from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from telegram_bot.config import MagnetImportConfig, magnet_import_config_from_dict
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.magnetboard_api import import_csv_sync, summarize_import_result
from telegram_bot.shared.telegram_download import document_name, document_size, download_document_resumable

from .base import ModuleCard

logger = logging.getLogger(__name__)

Importer = Callable[..., dict[str, Any]]
_STATE_LIMIT = 200


class MagnetImportModule:
    """监听指定群/用户发送的 CSV，下载后导入 MagnetBoard 并回复。"""

    def __init__(
        self,
        card: ModuleCard,
        config: MagnetImportConfig,
        project_root: Path | None = None,
        *,
        importer: Importer = import_csv_sync,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root or Path.cwd()
        self._importer = importer
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._in_progress: set[str] = set()
        self._state = self._load_state()
        self._sync_card_config()
        self.card.metrics = {"imported": int(self._state.get("imported", 0)), "last": self._state.get("last") or {}}

    async def start(self) -> None:
        self._clean_download_dir()
        self.card.status = "running"

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self.card.status = "stopped"

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def handle_message(self, event: Any) -> HandlerResult:
        if "MessageEdited" in type(event).__qualname__:
            return HandlerResult.ignored(self.card.id)
        message = getattr(event, "message", event)
        chat_id = str(getattr(message, "chat_id", getattr(event, "chat_id", "")) or "")
        if chat_id not in set(self.config.watch_chats):
            return HandlerResult.ignored(self.card.id)
        name = document_name(message)
        if not getattr(message, "document", None) or not name or not self._name_matches(name):
            return HandlerResult.ignored(self.card.id)
        if not await self._sender_matches(message):
            return HandlerResult.ignored(self.card.id)

        key = f"{chat_id}:{getattr(message, 'id', '')}"
        if key in self._in_progress or key in self._state.get("processed", {}):
            return HandlerResult.ignored(self.card.id)

        size = document_size(message)
        if size > self.config.max_file_size_mb * 1024 * 1024:
            logger.warning("Magnet import skipped oversized file %s (%s bytes)", name, size)
            self._record(key, name, "skipped", f"文件超过 {self.config.max_file_size_mb} MB")
            return HandlerResult.handled(self.card.id, "magnet import skipped oversized file")
        if not self.config.api_username or not self.config.api_password:
            logger.warning("Magnet import skipped %s: MagnetBoard username/password not configured", name)
            self._set_last(name, "failed", "未配置 MagnetBoard 用户名/密码")
            return HandlerResult.handled(self.card.id, "magnet import missing credentials")

        client = getattr(event, "client", None)
        if client is None or not hasattr(client, "iter_download"):
            return HandlerResult.failed(self.card.id, "Telegram client cannot download files")

        self._in_progress.add(key)
        task = asyncio.create_task(self._process(client, message, key, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("Magnet import queued: chat_id=%s message_id=%s file=%s size=%s", chat_id, message.id, name, size)
        return HandlerResult.handled(self.card.id, "magnet import queued", {"file": name, "size": size})

    async def _process(self, client: Any, message: Any, key: str, name: str) -> None:
        dest = self._download_dir() / f"{message.id}_{_safe_name(name)}"
        try:
            async with self._lock:
                self._set_last(name, "downloading", "")
                started = time.monotonic()
                size = await download_document_resumable(
                    client,
                    message,
                    dest,
                    retries=self.config.download_retries,
                    refetch=lambda: _refetch(client, message),
                    sleep=self._sleep,
                )
                logger.info("Magnet import downloaded %s (%s bytes) in %.1fs", name, size, time.monotonic() - started)

                self._set_last(name, "importing", "")
                payload = await asyncio.to_thread(
                    self._importer,
                    self.config.api_base_url,
                    self.config.api_username,
                    self.config.api_password,
                    dest,
                    name,
                    update_existing=self.config.update_existing,
                    skip_duplicates=self.config.skip_duplicates,
                    timeout=self.config.import_timeout_seconds,
                )
                summary = summarize_import_result(payload)
                logger.info("Magnet import finished %s: %s", name, summary)
                self._record(key, name, "imported", summary)

            if self.config.reply_text.strip():
                await client.send_message(message.chat_id, self.config.reply_text, reply_to=message.id)
        except asyncio.CancelledError:
            self._set_last(name, "cancelled", "服务停止，任务已取消")
            raise
        except Exception as exc:
            logger.exception("Magnet import failed for %s", name)
            self._set_last(name, "failed", str(exc)[:300])
        finally:
            self._in_progress.discard(key)
            for path in (dest, dest.with_name(dest.name + ".part")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Failed to remove magnet import temp file %s", path, exc_info=True)

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("magnet_import", values)
        if not isinstance(data, dict):
            return
        data = dict(data)
        # 后台不回显密码，留空表示保持原值
        if not str(data.get("api_password") or ""):
            data.pop("api_password", None)
        self.config = magnet_import_config_from_dict({**asdict(self.config), **data})
        self._sync_card_config()

    def _sync_card_config(self) -> None:
        config = asdict(self.config)
        config["api_password"] = ""
        config["has_api_password"] = bool(self.config.api_password)
        self.card.config = config

    def _name_matches(self, name: str) -> bool:
        try:
            return re.search(self.config.file_name_pattern, name, re.IGNORECASE) is not None
        except re.error:
            logger.warning("Invalid magnet import file_name_pattern: %s", self.config.file_name_pattern)
            return False

    async def _sender_matches(self, message: Any) -> bool:
        ids = {str(item).strip() for item in self.config.sender_ids if str(item).strip()}
        names = {item.lstrip("@").lower() for item in self.config.sender_usernames if item.strip()}
        if str(getattr(message, "sender_id", "")) in ids:
            return True
        if not names:
            return False
        sender = getattr(message, "sender", None)
        if sender is None and hasattr(message, "get_sender"):
            try:
                sender = await message.get_sender()
            except Exception:
                sender = None
        username = str(getattr(sender, "username", "") or "").lower()
        return bool(username) and username in names

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.project_root / path

    def _download_dir(self) -> Path:
        return self._resolve(self.config.download_dir)

    def _clean_download_dir(self) -> None:
        directory = self._download_dir()
        if not directory.is_dir():
            return
        for path in directory.iterdir():
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            except OSError:
                logger.warning("Failed to clean magnet import leftover %s", path, exc_info=True)

    def _load_state(self) -> dict[str, Any]:
        path = self._resolve(self.config.state_store)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"processed": {}, "imported": 0}
        if not isinstance(data, dict) or not isinstance(data.get("processed"), dict):
            return {"processed": {}, "imported": 0}
        return data

    def _save_state(self) -> None:
        path = self._resolve(self.config.state_store)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.warning("Failed to save magnet import state", exc_info=True)

    def _set_last(self, name: str, status: str, detail: str) -> None:
        last = {"file": name, "status": status, "detail": detail, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._state["last"] = last
        self.card.metrics = {"imported": int(self._state.get("imported", 0)), "last": last}
        if status not in {"downloading", "importing"}:
            self._save_state()

    def _record(self, key: str, name: str, status: str, detail: str) -> None:
        processed = self._state.setdefault("processed", {})
        processed[key] = {"file": name, "status": status, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        while len(processed) > _STATE_LIMIT:
            processed.pop(next(iter(processed)))
        if status == "imported":
            self._state["imported"] = int(self._state.get("imported", 0)) + 1
        self._set_last(name, status, detail)


async def _refetch(client: Any, message: Any) -> Any:
    if not hasattr(client, "get_messages"):
        return message
    return await client.get_messages(message.chat_id, ids=message.id)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name).strip("._")
    return cleaned[:120] or "data.csv"
