from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path

from telegram_bot.config import MagnetImportConfig, magnet_import_config_from_dict
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.magnet_avdb import build_record_hash_index, drop_duplicate_files
from telegram_bot.modules.magnet_import import MagnetImportModule
from telegram_bot.shared.avdb_release import ReleaseAsset, _body_sha256
from telegram_bot.shared.magnetboard_api import CSV_COLUMNS

SCRIPT_FIELDS = [
    "title", "url", "images", "magnets", "code", "size", "is_uncensored", "forum_id", "forum_type",
    "forum_name", "magnet_hash", "published_at", "created_at", "source_site", "cover_url", "tags", "categories",
]


def ed2k(file_hash: str) -> str:
    return json.dumps([f"ed2k://|file|a.mp4|1|{file_hash}|/"])


def script_row(avdb_id: str, file_hash: str, created: str, code: str = "ABC-001") -> dict[str, str]:
    row = dict.fromkeys(SCRIPT_FIELDS, "")
    row.update(title=f"标题 {code}", magnets=ed2k(file_hash), code=code, magnet_hash=avdb_id,
               created_at=created, source_site="sample", is_uncensored="true")
    return row


def export_text(records: list[tuple[int, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record_id, file_hash in records:
        writer.writerow({"id": record_id, "source_site": "sample", "magnets": ed2k(file_hash)})
    return out.getvalue()


class FakeRelease:
    def __init__(self, rows: list[dict[str, str]], tag: str = "2026-10-27-04-00-48") -> None:
        self.rows = rows
        self.tag = tag
        self.downloads = 0

    def latest(self, repo, pattern):
        assert repo == "example-org/sample-avdb" and pattern == r"^Sample_.*\.zip$"
        return ReleaseAsset(self.tag, f"Sample_{self.tag}.zip", "https://x", 0, "ab" * 32)

    def download(self, asset, dest):
        self.downloads += 1
        dest.write_bytes(b"zip")
        return dest

    def convert(self, script, zip_path):
        assert script.name == "resource_to_csv.sh"
        out = zip_path.with_suffix(".csv")
        with out.open("w", encoding="utf-8-sig", newline="") as fh:  # 与脚本一样带 BOM
            writer = csv.DictWriter(fh, fieldnames=SCRIPT_FIELDS)
            writer.writeheader()
            writer.writerows(self.rows)
        return out


class Importer:
    def __init__(self) -> None:
        self.files: list[bytes] = []

    def __call__(self, base_url, username, password, file_path, file_name, **kwargs):
        self.kwargs = kwargs
        content = Path(file_path).read_bytes()
        self.files.append(content)
        count = len(list(csv.DictReader(io.StringIO(content.decode("utf-8")))))
        return {"success": True, "data": {"imported_records": count, "skipped_records": 0, "error_records": 0}}


def make_module(tmp_path: Path, release: FakeRelease, importer: Importer, *, existing: str = "", **kwargs):
    deleted: dict[str, object] = {}

    def deleter(*args, **kw):
        deleted["source"] = kw
        return 5

    def record_deleter(base, user, pw, ids):
        deleted["ids"] = ids
        return len(ids)

    async def no_sleep(_):
        return None

    module = MagnetImportModule(
        ModuleCard("magnet_import", "magnet", "", "automation", enabled=True),
        MagnetImportConfig(api_password="secret", avdb_enabled=True, avdb_repo="example-org/sample-avdb", avdb_asset_pattern=r"^Sample_.*\.zip$", avdb_source_site="sample"),
        tmp_path,
        importer=importer,
        exporter=lambda *a, **k: existing or export_text([]),
        deleter=deleter,
        record_deleter=record_deleter,
        avdb_overrides={"latest": release.latest, "download": release.download, "convert": release.convert,
                        "sleep": no_sleep, "importer": importer, **kwargs},
    )
    module._running = True
    return module, deleted


def test_config_defaults() -> None:
    config = MagnetImportConfig()
    assert config.avdb_enabled is False and config.avdb_interval_hours == 4
    assert config.avdb_source_site == "" and config.channel_export_source_site == ""
    assert magnet_import_config_from_dict({"avdb_interval_hours": 0}).avdb_interval_hours == 1


def test_body_sha256_parsing() -> None:
    body = "文件 SHA-256：\\n- `Sample_662_x.zip`: `" + "A" * 64 + "`\n- `30D_LTX_x.zip`: `" + "b" * 64 + "`"
    assert _body_sha256(body, "Sample_662_x.zip") == "a" * 64
    assert _body_sha256(body, "missing.zip") == ""


def test_imports_new_release_without_bom_and_dedupes(tmp_path: Path) -> None:
    rows = [
        script_row("3", "c" * 32, "2026-10-23T03:00:00"),
        script_row("1", "a" * 32, "2026-10-23T01:00:00"),
        script_row("2", "a" * 32, "2026-10-23T02:00:00"),  # 与 #1 同文件，较晚 → 丢弃
        script_row("4", "e" * 32, "2026-10-23T04:00:00"),  # 与库内已有记录同文件 → 丢弃
    ]
    importer = Importer()
    module, _ = make_module(tmp_path, FakeRelease(rows), importer, existing=export_text([(10, "E" * 32)]))
    result = asyncio.run(module.avdb.run_once())
    assert result["status"] == "imported"
    assert "共 4 条" in result["detail"] and "同文件重复 2" in result["detail"] and "已校验" in result["detail"]
    content = importer.files[0]
    assert not content.startswith(b"\xef\xbb\xbf")
    imported = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    assert [row["magnet_hash"] for row in imported] == ["a" * 32, "c" * 32]  # 资源编号改为文件 MD4
    assert imported[0]["title"] == "标题 ABC-001"
    snapshot = module.card.metrics["avdb"]
    assert snapshot["last_tag"] == "2026-10-27-04-00-48" and snapshot["imported"] == 2
    assert snapshot["running"] is False
    assert not list((tmp_path / "runtime/tmp/magnet_import").iterdir())


def test_same_tag_is_skipped_unless_forced(tmp_path: Path) -> None:
    release = FakeRelease([script_row("1", "a" * 32, "2026-10-23")])
    importer = Importer()
    module, _ = make_module(tmp_path, release, importer)

    async def run():
        await module.avdb.run_once()
        second = await module.avdb.run_once()
        third = await module.avdb.run_once(force=True)
        return second, third

    second, third = asyncio.run(run())
    assert second["status"] == "unchanged"
    assert third["status"] == "imported"
    assert release.downloads == 2


def test_rebuild_deletes_source_without_hash_prefix(tmp_path: Path) -> None:
    importer = Importer()
    module, deleted = make_module(
        tmp_path, FakeRelease([script_row("1", "a" * 32, "2026-10-23")]), importer, existing=export_text([(10, "A" * 32)])
    )

    async def run():
        assert module.request_avdb_run(rebuild=True)
        assert not module.request_avdb_run()  # 运行中不能重复触发
        await module.avdb.wait_idle()

    asyncio.run(run())
    assert deleted["source"] == {"source_site": "sample"}  # 不限 url，频道记录一起删
    # 重建后不参考库内旧 hash，同文件的新数据照常导入
    assert "重建：删除旧记录 5 条" in module.card.metrics["avdb"]["last"]["detail"]
    assert len(importer.files) == 1


def test_update_existing_reimports_known_files(tmp_path: Path) -> None:
    rows = [
        script_row("1", "a" * 32, "2026-10-23T01:00:00"),  # 库内已有同文件，更新模式下照样提交以便更新
        script_row("2", "a" * 32, "2026-10-23T02:00:00"),  # 与 #1 同文件不同编号，仍丢弃
    ]
    importer = Importer()
    module, _ = make_module(tmp_path, FakeRelease(rows), importer, existing=export_text([(10, "A" * 32)]))

    async def run():
        assert module.request_avdb_run(update_existing=True)
        await module.avdb.wait_idle()

    asyncio.run(run())
    assert importer.kwargs["update_existing"] is True
    imported = list(csv.DictReader(io.StringIO(importer.files[0].decode("utf-8"))))
    assert [row["magnet_hash"] for row in imported] == ["a" * 32]
    assert "forum_name" in imported[0]
    assert module.card.metrics["avdb"]["last"]["detail"].startswith("更新已有记录")


def test_existing_duplicates_removed_keeping_lowest_record_id() -> None:
    index, duplicate_ids = build_record_hash_index(export_text([(30, "A" * 32), (10, "a" * 32), (20, "B" * 32)]), "sample")
    assert duplicate_ids == [30]
    assert index == {"ed2k:" + "a" * 32, "ed2k:" + "b" * 32}


def test_drop_duplicate_files_orders_by_created_at() -> None:
    rows = [script_row("late", "a" * 32, "2026-10-24"), script_row("early", "A" * 32, "2026-10-23")]
    kept, duplicates = drop_duplicate_files(rows, set())
    assert [row["magnet_hash"] for row in kept] == ["early"]
    assert [row["magnet_hash"] for row in duplicates] == ["late"]


def test_due_respects_interval_and_switch(tmp_path: Path) -> None:
    now = [100_000.0]
    module, _ = make_module(tmp_path, FakeRelease([]), Importer(), clock=lambda: now[0])
    avdb = module.avdb
    assert avdb.due()
    avdb.state["last_check_ts"] = now[0] - 3 * 3600
    assert not avdb.due()
    now[0] += 3600
    assert avdb.due()
    module.config.avdb_enabled = False
    assert not avdb.due()


def test_failure_is_reported(tmp_path: Path) -> None:
    release = FakeRelease([])

    def broken(script, zip_path):
        raise RuntimeError("转换失败：bad zip")

    module, _ = make_module(tmp_path, release, Importer(), convert=broken)
    result = asyncio.run(module.avdb.run_once())
    assert result["status"] == "failed" and "bad zip" in result["detail"]
    assert module.card.metrics["avdb"]["last_tag"] == ""
