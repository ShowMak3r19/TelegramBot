from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from telegram_bot.config import MagnetImportConfig, magnet_import_config_from_dict
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.magnetboard_api import (
    delete_records_sync,
    delete_source_records_sync,
    enrich_images_sync,
    export_csv_sync,
    import_csv_sync,
    import_posts_csv_sync,
    summarize_import_result,
)
from telegram_bot.shared.magnet_csv import CsvFormatError, normalize_import_csv
from telegram_bot.shared.telegram_download import document_name, document_size, download_document_resumable
from telegram_bot.shared.telegram_io import (
    atomic_write_text,
    get_reply_message,
    is_edited_event,
    is_outgoing,
    message_text,
    safe_edit_message,
    safe_filename_component,
)

from .base import ModuleCard
from .magnet_channel import ChannelMagnetImporter, HistoryReader
from .magnet_avdb import AvdbReleaseImporter
from .magnet_channel_export import ChannelExportJob, FileSender

logger = logging.getLogger(__name__)

Importer = Callable[..., dict[str, Any]]
_STATE_LIMIT = 200


class MagnetImportModule:
    """监听指定群/用户发送的 CSV，下载后导入 MagnetBoard 并回复；另含频道帖子来源（见 magnet_channel）。"""

    def __init__(
        self,
        card: ModuleCard,
        config: MagnetImportConfig,
        project_root: Path | None = None,
        *,
        importer: Importer = import_csv_sync,
        posts_importer: Importer = import_posts_csv_sync,
        enricher: Callable[..., dict[str, int]] = enrich_images_sync,
        exporter: Callable[..., str] = export_csv_sync,
        deleter: Callable[..., int] = delete_source_records_sync,
        record_deleter: Callable[..., int] = delete_records_sync,
        avdb_overrides: dict[str, Any] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root or Path.cwd()
        self._importer = importer
        self._posts_importer = posts_importer
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._in_progress: set[str] = set()
        self._state = self._load_state()
        self.channel = ChannelMagnetImporter(
            lambda: self.config,
            self._sub_state("channel"),
            self._on_channel_change,
            importer,
            self._download_dir,
            enricher=enricher,
            deleter=deleter,
            exporter=exporter,
            record_deleter=record_deleter,
            import_lock=self._lock,
        )
        self.avdb = AvdbReleaseImporter(
            lambda: self.config,
            self._sub_state("avdb"),
            self._on_channel_change,
            self._download_dir,
            self.project_root,
            exporter=exporter,
            deleter=deleter,
            record_deleter=record_deleter,
            import_lock=self._lock,
            on_imported=self.channel.reset_index,
            **(avdb_overrides or {}),
        )
        self.export_job = ChannelExportJob(
            lambda: self.config,
            self._sub_state("channel_export"),
            self._on_channel_change,
            self._download_dir,
            exporter=exporter,
        )
        self._running = False
        self._sync_card_config()
        self._refresh_metrics()

    def set_history_reader(self, reader: HistoryReader) -> None:
        self.channel.history_reader = reader

    def set_file_sender(self, sender: FileSender) -> None:
        self.export_job.file_sender = sender

    def request_channel_scan(self, *, full: bool, rebuild: bool = False) -> bool:
        """后台触发频道全量提取/全量重建/补漏；已在扫描或不可用时返回 False。"""
        if not self._running or not self.config.channel_enabled:
            return False
        started = self.channel.schedule_scan(full=full, rebuild=rebuild)
        self._refresh_metrics()
        return started

    def request_avdb_run(self, *, force: bool = False, rebuild: bool = False, update_existing: bool = False) -> bool:
        """后台“立即检查”/“删除并重建”/“更新已有记录”：后台任务执行，已在运行或模块未启用时返回 False。"""
        if not self._running:
            return False
        started = self.avdb.request_run(force=force, rebuild=rebuild, update_existing=update_existing)
        if started and rebuild:
            self.channel.reset_index()  # AVDB 重建会删掉同来源的频道记录，索引需重建
        self._refresh_metrics()
        return started

    async def run_channel_export(self) -> dict[str, Any]:
        """后台“立即导出发送”：不受定时开关限制，增量口径与定时任务相同。"""
        if not self._running:
            return {"status": "failed", "detail": "模块未启用"}
        result = await self.export_job.run_once(force=True)
        self._refresh_metrics()
        return result

    async def start(self) -> None:
        self._clean_download_dir()
        self._running = True
        self.card.status = "running"
        if self.config.channel_enabled:
            self.channel.schedule_scan(full=False)
        self.export_job.start()
        self.avdb.start()

    async def stop(self) -> None:
        self._running = False
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.channel.stop()
        self.channel.reset_index()  # 重新启用时按库里最新数据重建
        await self.export_job.stop()
        await self.avdb.stop()
        self.card.status = "stopped"
        self._refresh_metrics()

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        await self.channel.wait_idle()
        await self.avdb.wait_idle()

    async def handle_message(self, event: Any) -> HandlerResult:
        if is_edited_event(event):
            return HandlerResult.ignored(self.card.id)
        message = getattr(event, "message", event)
        chat_id = str(getattr(message, "chat_id", getattr(event, "chat_id", "")) or "")
        if self.channel.matches(chat_id):
            if self.channel.handle(message):
                return HandlerResult.handled(self.card.id, "channel magnet import queued", {"message_id": message.id})
            return HandlerResult.ignored(self.card.id)
        if chat_id not in set(self.config.watch_chats):
            return HandlerResult.ignored(self.card.id)
        if is_outgoing(event) and self._is_import_command(message_text(message)):
            return await self._handle_import_command(event, message, chat_id)
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
        chat_part = safe_filename_component(str(getattr(message, "chat_id", "")), fallback="chat")
        dest = self._download_dir() / f"{chat_part}_{message.id}_{secrets.token_hex(4)}_{_safe_name(name)}"
        clean = dest.with_name(dest.name + ".clean.csv")
        try:
            async with self._lock:
                try:
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

                    try:
                        check = await asyncio.to_thread(normalize_import_csv, dest, clean, self._hash_sources())
                    except CsvFormatError as exc:
                        logger.warning("Magnet import format check failed for %s: %s", name, exc)
                        self._set_last(name, "failed", f"格式校对未通过：{exc}")
                        return
                    logger.info("Magnet import checked %s: %s", name, check.describe())
                    if check.written == 0:
                        logger.warning("Magnet import has no valid rows for %s: %s", name, check.describe())
                        self._set_last(name, "failed", f"没有可导入的行：{check.describe()}")
                        return

                    self._set_last(name, "importing", "")
                    payload = await asyncio.to_thread(
                        self._importer,
                        self.config.api_base_url,
                        self.config.api_username,
                        self.config.api_password,
                        clean,
                        name,
                        update_existing=self.config.update_existing,
                        skip_duplicates=self.config.skip_duplicates,
                        timeout=self.config.import_timeout_seconds,
                    )
                    summary = summarize_import_result(payload)
                    logger.info("Magnet import finished %s: %s", name, summary)
                    self._record(key, name, "imported", summary)
                finally:
                    _remove_temp_files(dest, dest.with_name(dest.name + ".part"), clean)

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
            _remove_temp_files(dest, dest.with_name(dest.name + ".part"), clean)

    def _is_import_command(self, text: str) -> bool:
        first = text.split(maxsplit=1)[0].lower() if text.strip() else ""
        return first in {prefix.strip().lower() for prefix in self.config.import_command_prefixes if prefix.strip()}

    async def _handle_import_command(self, event: Any, command: Any, chat_id: str) -> HandlerResult:
        client = getattr(event, "client", None)
        replied = await get_reply_message(command)
        name = document_name(replied) if replied is not None else ""
        error = ""
        if replied is None or not getattr(replied, "document", None) or not name.lower().endswith(".csv"):
            error = "请回复一个 .csv 文件消息再发送 /import。"
        elif document_size(replied) > self.config.max_file_size_mb * 1024 * 1024:
            error = f"文件超过 {self.config.max_file_size_mb} MB，未导入。"
        elif not self.config.api_username or not self.config.api_password:
            error = "未配置 MagnetBoard 用户名/密码，无法导入。"
        elif client is None or not hasattr(client, "iter_download"):
            return HandlerResult.failed(self.card.id, "Telegram client cannot download files")
        key = f"{chat_id}:{getattr(replied, 'id', '')}"
        if not error and key in self._in_progress:
            error = "这个文件正在导入中，请稍候。"
        if error:
            if client is not None:
                await self._notify(client, command, replied, f"❌ {error}")
            return HandlerResult.handled(self.card.id, "magnet manual import rejected", {"reason": error})

        self._in_progress.add(key)
        if not await safe_edit_message(command, f"⏳ 正在导入 {name}：排队中…", parse_mode=None):
            command = None  # 编辑失败则结束时改为另发消息
        task = asyncio.create_task(self._process_manual(client, replied, key, name, command))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("Magnet manual import queued: chat_id=%s message_id=%s file=%s", chat_id, replied.id, name)
        return HandlerResult.handled(self.card.id, "magnet manual import queued", {"file": name})

    async def _notify(self, client: Any, status: Any, message: Any, text: str) -> None:
        """优先把 /import 消息原地编辑成 text，失败再回复 CSV 发新消息。"""
        if status is not None and await safe_edit_message(status, text, parse_mode=None):
            return
        source = message if message is not None else status
        await client.send_message(getattr(source, "chat_id", None), text, reply_to=getattr(message, "id", None))

    async def _process_manual(self, client: Any, message: Any, key: str, name: str, status: Any = None) -> None:
        chat_part = safe_filename_component(str(getattr(message, "chat_id", "")), fallback="chat")
        dest = self._download_dir() / f"{chat_part}_{message.id}_{secrets.token_hex(4)}_{_safe_name(name)}"
        clean = dest.with_name(dest.name + ".clean.csv")
        try:
            async with self._lock:
                try:
                    self._set_last(name, "downloading", "")
                    await safe_edit_message(status, f"⏳ 正在导入 {name}：下载中…", parse_mode=None)
                    await download_document_resumable(
                        client,
                        message,
                        dest,
                        retries=self.config.download_retries,
                        refetch=lambda: _refetch(client, message),
                        sleep=self._sleep,
                    )
                    await safe_edit_message(status, f"⏳ 正在导入 {name}：格式校对中…", parse_mode=None)
                    try:
                        check = await asyncio.to_thread(
                            normalize_import_csv, dest, clean, self._hash_sources(), allow_posts=True
                        )
                    except CsvFormatError as exc:
                        logger.warning("Magnet manual import format check failed for %s: %s", name, exc)
                        self._set_last(name, "failed", f"格式校对未通过：{exc}")
                        await self._notify(client, status, message, f"❌ {name} 格式校对未通过：{exc}")
                        return
                    logger.info("Magnet manual import checked %s (kind=%s): %s", name, check.kind, check.describe())
                    if check.written == 0:
                        self._set_last(name, "failed", f"没有可导入的行：{check.describe()}")
                        await self._notify(client, status, message, f"❌ {name} 没有可导入的行\n校对：{check.describe()}")
                        return

                    self._set_last(name, "importing", "")
                    if check.kind == "posts":
                        await safe_edit_message(
                            status,
                            f"⏳ 正在导入色花综合帖子 {name}：上传到 MagnetBoard（仅新增不覆盖）…\n校对：{check.describe()}",
                            parse_mode=None,
                        )
                        payload = await asyncio.to_thread(
                            self._posts_importer,
                            self.config.api_base_url,
                            self.config.api_username,
                            self.config.api_password,
                            clean,
                            name,
                            merge_strategy="add",
                            validate_data=True,
                            timeout=self.config.import_timeout_seconds,
                        )
                    else:
                        await safe_edit_message(
                            status, f"⏳ 正在导入 {name}：上传到 MagnetBoard…\n校对：{check.describe()}", parse_mode=None
                        )
                        payload = await asyncio.to_thread(
                            self._importer,
                            self.config.api_base_url,
                            self.config.api_username,
                            self.config.api_password,
                            clean,
                            name,
                            update_existing=self.config.update_existing,
                            skip_duplicates=True,  # 与库内重复交给 MagnetBoard 按 url 跳过
                            timeout=self.config.import_timeout_seconds,
                        )
                    summary = summarize_import_result(payload)
                    logger.info("Magnet manual import finished %s (kind=%s): %s", name, check.kind, summary)
                    self._record(f"{key}:manual", name, "imported", summary)
                finally:
                    _remove_temp_files(dest, dest.with_name(dest.name + ".part"), clean)
            target_prefix = "色花综合帖子 " if check.kind == "posts" else ""
            await self._notify(
                client,
                status,
                message,
                f"✅ 已导入 {target_prefix}{name}\n校对：{check.describe()}\n导入：{_import_stats_text(payload)}",
            )
        except asyncio.CancelledError:
            self._set_last(name, "cancelled", "服务停止，任务已取消")
            raise
        except Exception as exc:
            logger.exception("Magnet manual import failed for %s", name)
            self._set_last(name, "failed", str(exc)[:300])
            try:
                await self._notify(client, status, message, f"❌ {name} 导入失败：{str(exc)[:200]}")
            except Exception:
                logger.warning("Failed to send magnet manual import failure reply", exc_info=True)
        finally:
            self._in_progress.discard(key)
            _remove_temp_files(dest, dest.with_name(dest.name + ".part"), clean)

    def update_config(self, values: dict[str, Any]) -> None:
        data = values.get("magnet_import", values)
        if not isinstance(data, dict):
            return
        data = dict(data)
        # 后台不回显密码，留空表示保持原值
        if not str(data.get("api_password") or ""):
            data.pop("api_password", None)
        was_enabled = self.config.channel_enabled
        prev_source_site = self.config.channel_source_site
        prev_url_prefix = self.config.channel_url_prefix
        self.config = magnet_import_config_from_dict({**asdict(self.config), **data})
        if (
            self.config.channel_source_site != prev_source_site
            or self.config.channel_url_prefix != prev_url_prefix
        ):
            self.channel.reset_index()
        self._sync_card_config()
        if self._running and self.config.channel_enabled and not was_enabled:
            self.channel.schedule_scan(full=False)
        self._refresh_metrics()

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
        directory = self._download_dir().resolve()
        root = self.project_root.resolve()
        if root not in directory.parents:
            logger.warning("Skip cleaning magnet import download_dir outside project root: %s", directory)
            return
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
            atomic_write_text(path, json.dumps(self._state, ensure_ascii=False, indent=2))
        except OSError:
            logger.warning("Failed to save magnet import state", exc_info=True)

    def _set_last(self, name: str, status: str, detail: str) -> None:
        last = {"file": name, "status": status, "detail": detail, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._state["last"] = last
        self._refresh_metrics()
        if status not in {"downloading", "importing"}:
            self._save_state()

    def _sub_state(self, key: str) -> dict[str, Any]:
        if not isinstance(self._state.get(key), dict):
            self._state[key] = {}
        return self._state[key]

    def _hash_sources(self) -> frozenset[str]:
        """magnet_hash 需统一为文件 MD4 的来源（频道/AVDB 写入的来源）。"""
        config = self.config
        return frozenset(item for item in (config.channel_source_site, config.avdb_source_site) if item)

    def _on_channel_change(self) -> None:
        self._save_state()
        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        self.card.metrics = {
            "imported": int(self._state.get("imported", 0)),
            "last": self._state.get("last") or {},
            "channel": self.channel.snapshot(),
            "channel_export": self.export_job.snapshot(),
            "avdb": self.avdb.snapshot(),
        }

    def _record(self, key: str, name: str, status: str, detail: str) -> None:
        processed = self._state.setdefault("processed", {})
        processed[key] = {"file": name, "status": status, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        while len(processed) > _STATE_LIMIT:
            processed.pop(next(iter(processed)))
        if status == "imported":
            self._state["imported"] = int(self._state.get("imported", 0)) + 1
        self._set_last(name, status, detail)


def _import_stats_text(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    parts = [
        ("新增", ("imported_records", "posts_imported")),
        ("跳过", ("skipped_records", "posts_skipped")),
        ("更新", ("updated_records", "posts_updated")),
        ("错误", ("error_records", "errors")),
    ]
    items: list[str] = []
    for label, keys in parts:
        for key in keys:
            if key in data:
                val = len(data[key]) if isinstance(data[key], list) else data[key]
                items.append(f"{label} {val}")
                break
    return "，".join(items) or summarize_import_result(payload)


async def _refetch(client: Any, message: Any) -> Any:
    if not hasattr(client, "get_messages"):
        return message
    return await client.get_messages(message.chat_id, ids=message.id)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name).strip("._")
    return cleaned[:120] or "data.csv"


def _remove_temp_files(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove magnet import temp file %s", path, exc_info=True)
