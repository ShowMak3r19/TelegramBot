from __future__ import annotations

import asyncio
import csv
import io
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from telegram_bot.config import MagnetImportConfig
from telegram_bot.shared.magnet_post_parser import format_size, link_hashes, parse_magnet_post, primary_file_hash
from telegram_bot.shared.magnetboard_api import (
    CSV_COLUMNS,
    delete_records_sync,
    delete_source_records_sync,
    enrich_images_sync,
    export_csv_sync,
    write_import_csv,
)

logger = logging.getLogger(__name__)

HistoryReader = Callable[..., AsyncIterator[Any]]
_IMPORT_COLUMNS = [*CSV_COLUMNS, "forum_name"]
_LOCAL_TZ = timezone(timedelta(hours=8))  # MagnetBoard 的 published_at 存北京时间


def _ensure_large_csv_field_limit() -> None:
    limit = min(sys.maxsize, 2**31 - 1)
    while limit >= 131072:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


class ChannelMagnetImporter:
    """频道来源：把频道帖子转成 MagnetBoard CSV 行导入。

    实时消息逐条导入；启动时从 last_message_id 往后补漏；后台可手动触发全量。
    去重两层：频道会把同一文件重发成新消息（url 不同，MagnetBoard 拦不住），
    所以按 ed2k/btih 文件 hash 去重，保留最早的消息；同一条消息重复导入再由 MagnetBoard 按 url 跳过。
    hash 索引覆盖该来源全部记录（含 AVDB 等非频道记录，视为比任何消息都早，只跳过不删除）。
    """

    def __init__(
        self,
        get_config: Callable[[], MagnetImportConfig],
        state: dict[str, Any],
        save_state: Callable[[], None],
        importer: Callable[..., dict[str, Any]],
        work_dir: Callable[[], Path],
        *,
        enricher: Callable[..., dict[str, int]] = enrich_images_sync,
        deleter: Callable[..., int] = delete_source_records_sync,
        exporter: Callable[..., str] = export_csv_sync,
        record_deleter: Callable[..., int] = delete_records_sync,
        import_lock: asyncio.Lock | None = None,
    ) -> None:
        self._get_config = get_config
        self.state = state
        self._save_state = save_state
        self._importer = importer
        self._enricher = enricher
        self._deleter = deleter
        self._exporter = exporter
        self._record_deleter = record_deleter
        # 文件 hash → 最早的消息 id；None 表示尚未从 MagnetBoard 建立
        self._hash_index: dict[str, int] | None = None
        self._index_lock = asyncio.Lock()
        self._work_dir = work_dir
        self._lock = import_lock if import_lock is not None else asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._scan_task: asyncio.Task | None = None
        self._scanning = False
        self.history_reader: HistoryReader | None = None

    @property
    def config(self) -> MagnetImportConfig:
        return self._get_config()

    def _sync_chat(self) -> None:
        """频道换了（消息 id 不再连续）就从头开始：清空进度游标和 hash 索引。"""
        chat = self.config.channel_chat
        if self.state.get("chat") == chat:
            return
        if self.state.get("chat") is not None or self.state.get("last_message_id"):
            logger.warning("Channel magnet source changed to %s; resetting progress", chat)
        for key in ("last_message_id", "pending_from", "imported"):
            self.state.pop(key, None)
        self.state["chat"] = chat
        self._hash_index = None
        self._save_state()

    def matches(self, chat_id: str) -> bool:
        return self.config.channel_enabled and bool(self.config.channel_chat) and chat_id == self.config.channel_chat

    @property
    def scanning(self) -> bool:
        return self._scanning

    def snapshot(self) -> dict[str, Any]:
        return {
            "imported": int(self.state.get("imported", 0)),
            "last_message_id": int(self.state.get("last_message_id", 0)),
            "scanning": self.scanning,
            "last": self.state.get("last") or {},
        }

    def handle(self, message: Any) -> bool:
        """实时消息：能解析出链接就排队导入，返回是否已排队。"""
        row = self.build_row(message)
        if row is None:
            return False
        self._sync_chat()
        task = asyncio.create_task(self._import_live(row, int(message.id)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    def schedule_scan(self, *, full: bool, rebuild: bool = False) -> bool:
        """full=True 从第一条消息开始；rebuild=True 先删除该来源全部记录再全量导入。

        MagnetBoard 导入接口的 update_existing 对已有记录不生效（实测按 url/id 都只会跳过），
        所以解析规则变化（无码标记、补图）后只能删了重导。
        """
        if self.scanning or (self._scan_task is not None and not self._scan_task.done()) or self.history_reader is None:
            return False
        self._sync_chat()
        if full or rebuild:
            min_id = 0
        else:
            min_id = int(self.state.get("last_message_id", 0))
            pending = int(self.state.get("pending_from", 0))
            if pending:
                min_id = min(min_id, pending - 1)
        loop = asyncio.get_running_loop()
        self._scan_task = loop.create_task(self._scan(self.history_reader, min_id, full or rebuild, rebuild))
        self._scanning = True
        return True

    async def stop(self) -> None:
        tasks = list(self._tasks) + ([self._scan_task] if self._scan_task else [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._scan_task = None

    async def wait_idle(self) -> None:
        while self._tasks or (self._scan_task and not self._scan_task.done()):
            await asyncio.gather(*list(self._tasks), *([self._scan_task] if self._scan_task else []), return_exceptions=True)

    def build_row(self, message: Any) -> dict[str, Any] | None:
        post = parse_magnet_post(getattr(message, "message", None) or getattr(message, "text", "") or "")
        if post is None:
            return None
        config = self.config
        message_id = int(message.id)
        date = getattr(message, "date", None)
        published = date.astimezone(_LOCAL_TZ) if isinstance(date, datetime) else datetime.now(_LOCAL_TZ)
        return {
            "id": message_id,
            "title": post.title,
            "content": post.content,
            "url": f"{config.channel_url_prefix}/{message_id}",
            "magnets": post.links,
            "code": post.code,
            "size": format_size(post.size_bytes),
            "forum_id": config.channel_forum_id,
            "forum_type": config.channel_forum_type,
            # momo 口径：文件 MD4（与 AVDB、ltx_watch 等来源一致，momo 按 magnet_hash+source_site 去重）
            "magnet_hash": primary_file_hash("\n".join(post.links)) or f"{config.channel_source_site}-{message_id}",
            "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
            "created_at": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "source_site": config.channel_source_site,
            "is_uncensored": str(post.is_uncensored),
            "tags": post.tags,
            "forum_name": config.channel_forum_type,
            "_hashes": post.link_hashes,  # 仅用于去重，不写入 CSV
        }

    async def _import_live(self, row: dict[str, Any], message_id: int) -> None:
        try:
            kept, duplicates, staged = await self._drop_duplicates([row])
            if not kept:
                if not self._scanning:
                    self._advance(message_id)
                owner = duplicates[0][1]
                where = f"#{owner}" if owner else "库内已有记录"
                self._set_last("skipped", f"#{message_id} {row['code'] or '无番号'} 与 {where} 文件相同，已跳过")
                return
            result = await self._import_rows([row], f"live_{message_id}")
            self._commit_hashes(staged)
            if not self._scanning:
                self._advance(message_id)
            self._set_last("imported", f"#{message_id} {row['code'] or '无番号'} · {_result_text(result)}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Channel magnet import failed for message %s", message_id)
            pending = int(self.state.get("pending_from", 0))
            self.state["pending_from"] = min(pending, message_id) if pending else message_id
            self._set_last("failed", f"#{message_id} {str(exc)[:200]}")

    async def _scan(self, reader: HistoryReader, min_id: int, full: bool, rebuild: bool) -> None:
        label = ("全量重建" if rebuild else "全量提取") if full else "补漏"
        totals = {"imported_records": 0, "skipped_records": 0, "error_records": 0, "duplicate_posts": 0}
        scanned = 0
        scanned_max_id = min_id
        pending_before = int(self.state.get("pending_from", 0))
        batch: list[dict[str, Any]] = []
        try:
            if rebuild:
                deleted = await self._delete_existing()
                self._hash_index = None  # 按库里剩余记录（如 AVDB）重建
                self._set_last("scanning", f"{label}：已删除旧记录 {deleted} 条，开始重新导入")
            else:
                self._set_last("scanning", f"{label}开始（从消息 #{min_id} 之后）")
                await self._ensure_index()  # 启动补漏时即建立索引并清理已有重复
            async for message in reader(self.config.channel_chat, min_id=min_id):
                scanned += 1
                scanned_max_id = max(scanned_max_id, int(getattr(message, "id", 0) or 0))
                row = self.build_row(message)
                if row is not None:
                    batch.append(row)
                if len(batch) >= self.config.channel_batch_size:
                    await self._flush(batch, totals, label)
                    batch = []
            if batch:
                await self._flush(batch, totals, label)
            current_pending = int(self.state.get("pending_from", 0))
            if current_pending and (current_pending == pending_before or scanned_max_id >= current_pending):
                self.state.pop("pending_from", None)
            self._scanning = False
            self._set_last("imported", f"{label}完成：扫描 {scanned} 条 · {_result_text({'data': totals})}")
            logger.info("Channel magnet %s finished: scanned=%s %s", label, scanned, totals)
        except asyncio.CancelledError:
            self._scanning = False
            self._set_last("cancelled", f"{label}已取消（已扫描 {scanned} 条）")
            raise
        except Exception as exc:
            logger.exception("Channel magnet %s failed", label)
            self._scanning = False
            self._set_last("failed", f"{label}失败（已扫描 {scanned} 条）：{str(exc)[:200]}")

    async def _flush(self, batch: list[dict[str, Any]], totals: dict[str, int], label: str) -> None:
        kept, duplicates, staged = await self._drop_duplicates(batch)
        totals["duplicate_posts"] += len(duplicates)
        if kept:
            result = await self._import_rows(kept, f"scan_{kept[0]['id']}_{kept[-1]['id']}")
            self._commit_hashes(staged)
            data = _result_data(result)
            for key in ("imported_records", "skipped_records", "error_records"):
                totals[key] += int(data.get(key) or 0)
        self._advance(max(int(row["id"]) for row in batch))
        self._set_last("scanning", f"{label}进行中：已到消息 #{batch[-1]['id']} · {_result_text({'data': totals})}")

    async def _drop_duplicates(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]], dict[str, int]]:
        """去掉与更早消息文件相同的行，返回 (保留行, [(重复行, 最早消息 id)], 待提交的 hash 映射)。"""
        index = await self._ensure_index()
        staged: dict[str, int] = {}
        kept: list[dict[str, Any]] = []
        duplicates: list[tuple[dict[str, Any], int]] = []
        for row in rows:
            message_id = int(row["id"])
            owners: list[int] = []
            for h in row.get("_hashes") or []:
                existing = staged.get(h, index.get(h))
                if existing is not None and existing != message_id:
                    owners.append(existing)
            earlier = [owner for owner in owners if owner < message_id]
            if earlier:
                duplicates.append((row, min(earlier)))
                continue
            for item in row.get("_hashes") or []:
                current = staged.get(item, index.get(item, message_id))
                staged[item] = min(current, message_id)
            kept.append(row)
        if duplicates:
            reposts = [f"#{row['id']}=#{owner}" for row, owner in duplicates if owner]
            logger.info(
                "Channel magnet skipped %s duplicate posts (%s already in library)%s",
                len(duplicates),
                len(duplicates) - len(reposts),
                f": {', '.join(reposts)}" if reposts else "",
            )
        return kept, duplicates, staged

    def _commit_hashes(self, staged: dict[str, int]) -> None:
        if self._hash_index is None or not staged:
            return
        for item, message_id in staged.items():
            self._hash_index[item] = min(self._hash_index.get(item, message_id), message_id)

    async def _ensure_index(self) -> dict[str, int]:
        """首次使用时从 MagnetBoard 导出该来源记录建立 hash 索引，并删掉已存在的重复（保留最早消息）。"""
        async with self._index_lock:
            if self._hash_index is not None:
                return self._hash_index
            config = self.config
            if not config.api_username or not config.api_password:
                raise RuntimeError("未配置 MagnetBoard 用户名/密码")
            text = await asyncio.to_thread(
                self._exporter,
                config.api_base_url,
                config.api_username,
                config.api_password,
                source_site=config.channel_source_site,
                timeout=config.import_timeout_seconds,
            )
            index, duplicate_ids = await asyncio.to_thread(
                build_hash_index, text, config.channel_source_site, config.channel_url_prefix
            )
            if duplicate_ids:
                await asyncio.to_thread(
                    self._record_deleter, config.api_base_url, config.api_username, config.api_password, duplicate_ids
                )
                logger.warning("Channel magnet removed %s existing duplicate records: %s", len(duplicate_ids), duplicate_ids)
            self._hash_index = index
            return index

    async def _delete_existing(self) -> int:
        config = self.config
        if not config.api_username or not config.api_password:
            raise RuntimeError("未配置 MagnetBoard 用户名/密码")
        async with self._lock:
            deleted = await asyncio.to_thread(
                self._deleter,
                config.api_base_url,
                config.api_username,
                config.api_password,
                source_site=config.channel_source_site,
                url_prefix=f"{config.channel_url_prefix}/",
            )
        logger.warning("Channel magnet rebuild deleted %s existing records of %s", deleted, config.channel_source_site)
        self.state["imported"] = 0
        return int(deleted)

    async def _import_rows(self, rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        config = self.config
        if not config.api_username or not config.api_password:
            raise RuntimeError("未配置 MagnetBoard 用户名/密码")
        directory = self._work_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"channel_{name}.csv"
        async with self._lock:
            if config.channel_enrich_images:
                await self._enrich(rows)
            try:
                await asyncio.to_thread(write_import_csv, rows, path, _IMPORT_COLUMNS)
                result = await asyncio.to_thread(
                    self._importer,
                    config.api_base_url,
                    config.api_username,
                    config.api_password,
                    path,
                    path.name,
                    update_existing=config.update_existing,
                    skip_duplicates=config.skip_duplicates,
                    timeout=config.import_timeout_seconds,
                )
            finally:
                path.unlink(missing_ok=True)
        self.state["imported"] = int(self.state.get("imported", 0)) + int(_result_data(result).get("imported_records") or 0)
        return result

    def reset_index(self) -> None:
        self._hash_index = None

    async def _enrich(self, rows: list[dict[str, Any]]) -> None:
        """按番号补封面/图片；补图失败不影响导入。"""
        config = self.config
        try:
            stats = await asyncio.to_thread(
                self._enricher,
                config.api_base_url,
                config.api_username,
                config.api_password,
                rows,
                exclude_source=config.channel_source_site,
            )
            logger.info("Channel magnet images enriched: %s", stats)
        except Exception:
            logger.warning("Channel magnet image enrichment failed; importing without images", exc_info=True)

    def _advance(self, message_id: int) -> None:
        if message_id > int(self.state.get("last_message_id", 0)):
            self.state["last_message_id"] = message_id
        self._save_state()

    def _set_last(self, status: str, detail: str) -> None:
        self.state["last"] = {"status": status, "detail": detail, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._save_state()


def _result_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _result_text(payload: dict[str, Any]) -> str:
    data = _result_data(payload)
    text = f"新增 {int(data.get('imported_records') or 0)} · 跳过 {int(data.get('skipped_records') or 0)} · 错误 {int(data.get('error_records') or 0)}"
    duplicates = int(data.get("duplicate_posts") or 0)
    return f"{text} · 重复帖 {duplicates}" if duplicates else text


def build_hash_index(text: str, source_site: str, url_prefix: str) -> tuple[dict[str, int], list[int]]:
    """从导出 CSV 建立 文件hash→最早消息id，并找出与更早记录文件相同的频道记录（返回其库内 id）。

    频道记录按 url `<url_prefix>/<消息id>` 识别（2026-11-06 起 magnet_hash 改为文件 MD4）；
    同来源的其他记录（如 AVDB）消息 id 记为 0，即比任何频道消息都早：新帖与它们文件相同就跳过，
    但它们自身不会被列为待删除。
    """
    _ensure_large_csv_field_limit()
    prefix = f"{url_prefix.rstrip('/')}/"
    records: list[tuple[int, int, list[str]]] = []
    for row in csv.DictReader(io.StringIO(text)):
        url = row.get("url") or ""
        suffix = url[len(prefix):] if url.startswith(prefix) else ""
        if row.get("source_site") != source_site or not str(row.get("id") or "").isdigit():
            continue
        message_id = int(suffix) if suffix.isdigit() else 0
        records.append((message_id, int(row["id"]), link_hashes(row.get("magnets") or "")))
    records.sort()
    index: dict[str, int] = {}
    duplicate_ids: list[int] = []
    for message_id, record_id, hashes in records:
        if any(h in index for h in hashes):
            if message_id:
                duplicate_ids.append(record_id)
            continue
        for item in hashes:
            index[item] = message_id
    return index, duplicate_ids
