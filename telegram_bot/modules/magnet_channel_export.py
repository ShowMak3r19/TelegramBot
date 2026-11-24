from __future__ import annotations

import asyncio
import csv
import io
import logging
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot.config import MagnetImportConfig
from telegram_bot.shared.magnet_post_parser import normalize_magnet_hash
from telegram_bot.shared.magnetboard_api import export_csv_sync
from telegram_bot.shared.telegram_io import safe_filename_component

logger = logging.getLogger(__name__)

FileSender = Callable[[str, Path, str], Awaitable[Any]]
_LOCAL_TZ = timezone(timedelta(hours=8))
_DUE_WINDOW = timedelta(minutes=15)
_TICK_SECONDS = 30.0


def _ensure_large_csv_field_limit() -> None:
    limit = min(sys.maxsize, 2**31 - 1)
    while limit >= 131072:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


class ChannelExportJob:
    """把 channel_export_source_site 来源的全部记录从 MagnetBoard 导出为 CSV 发到群（全量，避免漏发）。

    定时任务：自上次发送后有新记录（MagnetBoard 记录 id 大于上次已发送的最大 id）才发；
    后台“立即导出并发送”：总是发送。删除重建会产生新 id，因此重建后的下一次定时会发送。
    """

    def __init__(
        self,
        get_config: Callable[[], MagnetImportConfig],
        state: dict[str, Any],
        save_state: Callable[[], None],
        work_dir: Callable[[], Path],
        *,
        exporter: Callable[..., str] = export_csv_sync,
        clock: Callable[[], datetime] = lambda: datetime.now(_LOCAL_TZ),
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._get_config = get_config
        self.state = state
        self._save_state = save_state
        self._work_dir = work_dir
        self._exporter = exporter
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.file_sender: FileSender | None = None

    @property
    def config(self) -> MagnetImportConfig:
        return self._get_config()

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_record_id": int(self.state.get("last_record_id", 0)),
            "last": self.state.get("last") or {},
            "running": self._lock.locked(),
        }

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def due_slot(self, now: datetime) -> str | None:
        """到点（且 15 分钟窗口内、本周期未执行过）时返回周期标识，否则 None；支持跨午夜窗口。"""
        config = self.config
        if not config.channel_export_enabled:
            return None
        hour, minute = (int(part) for part in config.channel_export_time.split(":"))
        for day_offset in (0, -1):
            candidate_day = now + timedelta(days=day_offset)
            if candidate_day.weekday() != config.channel_export_weekday:
                continue
            slot = candidate_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            key = slot.strftime("%Y-%m-%d %H:%M")
            if slot <= now < slot + _DUE_WINDOW and self.state.get("last_slot") != key:
                return key
        return None

    async def run_once(self, *, force: bool = False) -> dict[str, Any]:
        """全量导出并发送一次；force=False 时没有新记录则不发。返回 {"status": sent|empty|failed, ...}。"""
        if self._lock.locked():
            return {"status": "busy"}
        async with self._lock:
            try:
                result = await self._export_and_send(force=force)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Channel magnet weekly export failed")
                result = {"status": "failed", "detail": str(exc)[:200]}
            self.state["last"] = {**result, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            self._save_state()
            return result

    async def _loop(self) -> None:
        while True:
            try:
                slot = self.due_slot(self._clock())
                if slot is not None:
                    result = await self.run_once()
                    if result.get("status") in {"sent", "empty"}:
                        self.state["last_slot"] = slot
                        self._save_state()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Channel magnet export scheduler tick failed")
            await self._sleep(_TICK_SECONDS)

    async def _export_and_send(self, *, force: bool) -> dict[str, Any]:
        config = self.config
        if not config.api_username or not config.api_password:
            raise RuntimeError("未配置 MagnetBoard 用户名/密码")
        if self.file_sender is None:
            raise RuntimeError("Telegram 未连接，无法发送文件")
        source_site = config.channel_export_source_site
        text = await asyncio.to_thread(
            self._exporter,
            config.api_base_url,
            config.api_username,
            config.api_password,
            source_site=source_site,
            timeout=config.import_timeout_seconds,
        )
        recorded_site = self.state.get("source_site")
        last_id = int(self.state.get("last_record_id", 0)) if recorded_site in {None, "", source_site} else 0
        fieldnames, rows = await asyncio.to_thread(_prepare_export_rows, text, source_site)
        if not rows:
            return {"status": "empty", "detail": f"来源 {source_site} 没有记录，未发送"}
        max_id = rows[-1][0]
        if not force and max_id <= last_id:
            return {"status": "empty", "detail": f"自上次发送（记录 #{last_id}）后没有新记录，未发送"}
        new_count = sum(1 for record_id, _ in rows if record_id > last_id)
        directory = self._work_dir()
        directory.mkdir(parents=True, exist_ok=True)
        safe_site = safe_filename_component(source_site, fallback="export")
        path = directory / f"{safe_site}_{self._clock().strftime('%Y-%m-%d')}_{secrets.token_hex(4)}.csv"
        try:
            await asyncio.to_thread(_write_export_csv, path, fieldnames, rows)
            caption = (
                f"{source_site} 全量 {len(rows)} 条（本次新增 {new_count} 条），"
                "可在 MagnetBoard「资源导入」中导入，已有记录会自动跳过"
            )
            await self.file_sender(config.channel_export_chat, path, caption)
        finally:
            path.unlink(missing_ok=True)
        self.state["source_site"] = source_site
        self.state["last_record_id"] = max_id
        logger.info("Magnet export sent: rows=%s new=%s max record id=%s", len(rows), new_count, max_id)
        return {"status": "sent", "detail": f"已发送全量 {len(rows)} 条（新增 {new_count} 条）"}


def _prepare_export_rows(text: str, source_site: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    fieldnames, rows = select_source_rows(text, source_site)
    for _, row in rows:  # 保险：库里若还有旧口径记录，发出去的也是文件 MD4
        normalize_magnet_hash(row, {source_site})
    return fieldnames, rows


def _write_export_csv(path: Path, fieldnames: list[str], rows: list[tuple[int, dict[str, str]]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row for _, row in rows)


def select_source_rows(text: str, source_site: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """从导出 CSV 中挑出该来源的全部行，按记录 id 升序。"""
    _ensure_large_csv_field_limit()
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple[int, dict[str, str]]] = []
    for row in reader:
        record_id = str(row.get("id") or "")
        if row.get("source_site") == source_site and record_id.isdigit():
            rows.append((int(record_id), row))
    rows.sort(key=lambda item: item[0])
    return list(reader.fieldnames or []), rows
