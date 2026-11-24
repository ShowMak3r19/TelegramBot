from __future__ import annotations

import asyncio
import csv
import io
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot.config import MagnetImportConfig
from telegram_bot.shared import avdb_release
from telegram_bot.shared.magnet_post_parser import link_hashes, normalize_magnet_hash
from telegram_bot.shared.magnetboard_api import (
    delete_records_sync,
    delete_source_records_sync,
    export_csv_sync,
    import_resource_csv_sync,
)
from telegram_bot.shared.telegram_io import safe_filename_component

logger = logging.getLogger(__name__)

_TICK_SECONDS = 60.0
_FAILURE_BACKOFF_SECONDS = 900.0
_CHUNK_ROWS = 2000
# MagnetBoard 用秒级时间戳命名导入临时表，同一秒内两次导入会冲突
_IMPORT_GAP_SECONDS = 2.0


def _ensure_large_csv_field_limit() -> None:
    limit = min(sys.maxsize, 2**31 - 1)
    while limit >= 131072:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


class AvdbReleaseImporter:
    """定时检查 AVDB GitHub release，有新版本时下载资源包、转 CSV、按文件 hash 去重后导入 MagnetBoard。

    去重：先用导出接口取该来源已有记录的 ed2k/btih hash（库内重复按记录 id 保留最早、删除较晚的），
    新数据里与已有记录或更早的新记录文件相同的行不导入；同一资源再次导入由 MagnetBoard 按资源编号跳过。

    导入走 MagnetBoard 的“外部来源资源导入”任务接口（/api/data/import-jobs），它会写 forum_name、
    计算 import_identity，并支持 update_existing 更新已有记录。
    """

    def __init__(
        self,
        get_config: Callable[[], MagnetImportConfig],
        state: dict[str, Any],
        save_state: Callable[[], None],
        work_dir: Callable[[], Path],
        project_root: Path,
        *,
        importer: Callable[..., dict[str, Any]] = import_resource_csv_sync,
        exporter: Callable[..., str] = export_csv_sync,
        deleter: Callable[..., int] = delete_source_records_sync,
        record_deleter: Callable[..., int] = delete_records_sync,
        latest: Callable[..., avdb_release.ReleaseAsset] = avdb_release.latest_asset_sync,
        download: Callable[..., Path] = avdb_release.download_asset_sync,
        convert: Callable[..., Path] = avdb_release.convert_zip_sync,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        import_lock: asyncio.Lock | None = None,
        on_imported: Callable[[], None] | None = None,
    ) -> None:
        self._get_config = get_config
        self.state = state
        self._save_state = save_state
        self._work_dir = work_dir
        self._project_root = project_root
        self._importer = importer
        self._exporter = exporter
        self._deleter = deleter
        self._record_deleter = record_deleter
        self._latest = latest
        self._download = download
        self._convert = convert
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._import_lock = import_lock if import_lock is not None else asyncio.Lock()
        self._on_imported = on_imported
        self._retry_after_ts: float = 0.0
        self._loop_task: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None

    @property
    def config(self) -> MagnetImportConfig:
        return self._get_config()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_tag": self.state.get("last_tag", ""),
            "last_check_at": self.state.get("last_check_at", ""),
            "imported": int(self.state.get("imported", 0)),
            "running": self.running,
            "last": self.state.get("last") or {},
        }

    def start(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        tasks = [task for task in (self._loop_task, self._run_task) if task is not None]
        self._loop_task = self._run_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_idle(self) -> None:
        if self._run_task is not None:
            await asyncio.gather(self._run_task, return_exceptions=True)

    def request_run(self, *, force: bool = False, rebuild: bool = False, update_existing: bool = False) -> bool:
        """后台按钮：立即检查（force 忽略版本号）、删除重建或更新已有记录；已在运行时返回 False。"""
        if self.running or (self._run_task is not None and not self._run_task.done()):
            return False
        self._run_task = asyncio.create_task(
            self.run_once(force=force, rebuild=rebuild, update_existing=update_existing)
        )
        return True

    def due(self) -> bool:
        if not self.config.avdb_enabled:
            return False
        now = self._clock()
        if self._retry_after_ts and now < self._retry_after_ts:
            return False
        last = float(self.state.get("last_check_ts") or 0)
        return now - last >= self.config.avdb_interval_hours * 3600

    async def _loop(self) -> None:
        while True:
            try:
                if self.due() and not self.running:
                    await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AVDB release scheduler tick failed")
            await self._sleep(_TICK_SECONDS)

    async def run_once(
        self, *, force: bool = False, rebuild: bool = False, update_existing: bool = False
    ) -> dict[str, Any]:
        if self._lock.locked():
            return {"status": "busy", "detail": "已有任务在运行"}
        async with self._lock:
            try:
                result = await self._run(
                    force=force or rebuild or update_existing, rebuild=rebuild, update_existing=update_existing
                )
                self._retry_after_ts = 0.0
            except asyncio.CancelledError:
                self._set_last("cancelled", "任务已取消")
                raise
            except Exception as exc:
                logger.exception("AVDB release import failed")
                self._retry_after_ts = self._clock() + _FAILURE_BACKOFF_SECONDS
                result = {"status": "failed", "detail": str(exc)[:300]}
            self._set_last(result["status"], result["detail"])
        self._save_state()  # 锁已释放，刷新后台显示的 running 状态
        return result

    async def _run(self, *, force: bool, rebuild: bool, update_existing: bool) -> dict[str, Any]:
        config = self.config
        if not config.api_username or not config.api_password:
            raise RuntimeError("未配置 MagnetBoard 用户名/密码")
        self._set_last("running", "检查 GitHub release…")
        asset = await asyncio.to_thread(self._latest, config.avdb_repo, config.avdb_asset_pattern)
        self.state["last_check_ts"] = self._clock()
        self.state["last_check_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if not force and asset.tag == self.state.get("last_tag"):
            return {"status": "unchanged", "detail": f"无更新（当前版本 {asset.tag}）"}

        work_root = self._work_dir()
        work_root.mkdir(parents=True, exist_ok=True)
        safe_tag = safe_filename_component(asset.tag, fallback="latest")
        safe_asset_name = safe_filename_component(asset.name, fallback="release.zip")
        script_path = self._resolve_converter_script(config.avdb_converter_script)

        with tempfile.TemporaryDirectory(prefix=f"avdb_{safe_tag}_", dir=work_root) as tmp_dir:
            directory = Path(tmp_dir).resolve()
            zip_target = (directory / safe_asset_name).resolve()
            if directory not in zip_target.parents:
                raise RuntimeError(f"非法的资源包文件名：{asset.name}")
            self._set_last("running", f"下载 {asset.name}…")
            zip_path = await asyncio.to_thread(self._download, asset, zip_target)
            self._set_last("running", f"转换 {asset.name}…")
            if self._convert is avdb_release.convert_zip_sync:
                csv_path = await asyncio.to_thread(
                    self._convert, script_path, zip_path, allowed_root=self._project_root
                )
            else:
                csv_path = await asyncio.to_thread(self._convert, script_path, zip_path)
            fieldnames, rows = await asyncio.to_thread(_read_and_normalize_csv, csv_path, config.avdb_source_site)

            async with self._import_lock:
                deleted = 0
                if rebuild:
                    deleted = await asyncio.to_thread(
                        self._deleter,
                        config.api_base_url,
                        config.api_username,
                        config.api_password,
                        source_site=config.avdb_source_site,
                    )
                    index: set[str] = set()
                else:
                    index = await self._existing_index()
                if update_existing:
                    # 更新模式：已有记录的 hash 也在索引里，只拦“同文件不同资源编号”的重复
                    kept, duplicates = await asyncio.to_thread(drop_duplicate_files, rows, set())
                else:
                    kept, duplicates = await asyncio.to_thread(drop_duplicate_files, rows, index)
                totals = await self._import(fieldnames, kept, directory, safe_tag, update_existing)
                if self._on_imported is not None:
                    self._on_imported()

        self.state["last_tag"] = asset.tag
        self.state["imported"] = int(self.state.get("imported", 0)) + totals["imported_records"]
        prefix = f"重建：删除旧记录 {deleted} 条 · " if rebuild else ("更新已有记录 · " if update_existing else "")
        detail = (
            f"{prefix}{asset.name}（{'已校验' if asset.sha256 else '未校验'}）共 {len(rows)} 条 · "
            f"新增 {totals['imported_records']} · 更新 {totals['updated_records']} · "
            f"跳过 {totals['skipped_records']} · 错误 {totals['error_records']} · 同文件重复 {len(duplicates)}"
        )
        logger.info("AVDB release imported: %s", detail)
        return {"status": "imported", "detail": detail}

    async def _existing_index(self) -> set[str]:
        config = self.config
        text = await asyncio.to_thread(
            self._exporter,
            config.api_base_url,
            config.api_username,
            config.api_password,
            source_site=config.avdb_source_site,
            timeout=config.import_timeout_seconds,
        )
        index, duplicate_ids = await asyncio.to_thread(build_record_hash_index, text, config.avdb_source_site)
        if duplicate_ids:
            await asyncio.to_thread(
                self._record_deleter, config.api_base_url, config.api_username, config.api_password, duplicate_ids
            )
            logger.warning("AVDB removed %s existing duplicate records: %s", len(duplicate_ids), duplicate_ids)
        return index

    async def _import(
        self, fieldnames: list[str], rows: list[dict[str, str]], directory: Path, tag: str, update_existing: bool
    ) -> dict[str, int]:
        config = self.config
        safe_site = safe_filename_component(config.avdb_source_site, fallback="avdb")
        safe_tag = safe_filename_component(tag, fallback="latest")
        totals = {"imported_records": 0, "updated_records": 0, "skipped_records": 0, "error_records": 0}
        for number, start in enumerate(range(0, len(rows), _CHUNK_ROWS), 1):
            if number > 1:
                await self._sleep(_IMPORT_GAP_SECONDS)
            path = (directory / f"{safe_site}_{safe_tag}_{number}.csv").resolve()
            if directory not in path.parents:
                raise RuntimeError(f"非法的分批导出文件名：{path.name}")
            # 脚本输出带 BOM，MagnetBoard 会因此读不到第一列 title，这里写成无 BOM 的 UTF-8
            await asyncio.to_thread(_write_csv_chunk, path, fieldnames, rows[start : start + _CHUNK_ROWS])
            self._set_last("running", f"导入第 {number} 批（{min(start + _CHUNK_ROWS, len(rows))}/{len(rows)}）…")
            payload = await asyncio.to_thread(
                self._importer,
                config.api_base_url,
                config.api_username,
                config.api_password,
                path,
                path.name,
                update_existing=update_existing,
                timeout=config.import_timeout_seconds,
            )
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for key in totals:
                totals[key] += int(data.get(key) or 0)
        return totals

    def _resolve_converter_script(self, value: str) -> Path:
        root = self._project_root.resolve()
        resolved = self._resolve(value).resolve()
        if root not in resolved.parents and resolved != root:
            raise RuntimeError(f"转换脚本路径越界：{value}")
        return resolved

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self._project_root / path

    def _set_last(self, status: str, detail: str) -> None:
        self.state["last"] = {"status": status, "detail": detail, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._save_state()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    _ensure_large_csv_field_limit()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _read_and_normalize_csv(path: Path, source_site: str) -> tuple[list[str], list[dict[str, str]]]:
    fieldnames, rows = _read_csv(path)
    # 脚本写的 magnet_hash 是 AVDB 资源编号，改成 momo 口径的文件 MD4，避免与其他来源重复入库
    if "magnet_hash" not in fieldnames:
        fieldnames.append("magnet_hash")
    sources = {source_site}
    for row in rows:
        normalize_magnet_hash(row, sources)
    return fieldnames, rows


def _write_csv_chunk(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def drop_duplicate_files(
    rows: list[dict[str, str]], index: set[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """按 created_at 从早到晚处理，与已有记录或更早新行文件相同的行丢弃（保留最早）。"""
    kept: list[dict[str, str]] = []
    duplicates: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: (item.get("created_at") or "", item.get("magnet_hash") or "")):
        hashes = link_hashes(row.get("magnets") or "")
        if any(item in index for item in hashes):
            duplicates.append(row)
            continue
        index.update(hashes)
        kept.append(row)
    return kept, duplicates


def build_record_hash_index(text: str, source_site: str) -> tuple[set[str], list[int]]:
    """从导出 CSV 建该来源的文件 hash 集合；同文件多条时按记录 id 保留最早，返回较晚记录的 id。"""
    _ensure_large_csv_field_limit()
    records: list[tuple[int, list[str]]] = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("source_site") == source_site and str(row.get("id") or "").isdigit():
            records.append((int(row["id"]), link_hashes(row.get("magnets") or "")))
    records.sort()
    index: set[str] = set()
    duplicate_ids: list[int] = []
    for record_id, hashes in records:
        if any(item in index for item in hashes):
            duplicate_ids.append(record_id)
            continue
        index.update(hashes)
    return index, duplicate_ids
