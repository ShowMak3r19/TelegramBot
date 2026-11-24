from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.config import MagnetImportConfig, magnet_import_config_from_dict
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.magnet_channel_export import select_source_rows
from telegram_bot.modules.magnet_import import MagnetImportModule
from telegram_bot.shared.magnet_post_parser import extract_code, format_size, parse_magnet_post
from telegram_bot.shared.magnetboard_api import CSV_COLUMNS

CHANNEL = "-1000000000005"
ED2K = "ed2k://|file|www.98T.la@mide307_restored.mp4|8754846010|BA2E92C0F1F9719532448EED72DF6DF2|h=SHBW3R4QRRYL6HPCA34FISIUEHMO57A3|/"
POST = f"MIDE-307 奴隷人妻拍賣會 沖田杏梨\n\n這裡是有錢資產家們聚集的秘密俱樂部\n\n{ED2K}"


class CsvImporter:
    def __init__(self, error: Exception | None = None) -> None:
        self.rows: list[list[dict[str, str]]] = []
        self.error = error

    def __call__(self, base_url, username, password, file_path, file_name, **kwargs):
        self.kwargs = kwargs
        text = Path(file_path).read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))
        assert reader.fieldnames == [*CSV_COLUMNS, "forum_name"]
        rows = list(reader)
        self.rows.append(rows)
        if self.error:
            raise self.error
        return {"success": True, "data": {"imported_records": len(rows), "skipped_records": 0, "error_records": 0}}


def post_for(message_id: int) -> str:
    """每条消息一个不同的文件 hash，避免被文件去重拦下。"""
    return POST.replace("BA2E92C0F1F9719532448EED72DF6DF2", f"{message_id:032X}")


def make_message(message_id: int, text: str | None = None, chat_id: str = CHANNEL):
    return SimpleNamespace(
        id=message_id,
        chat_id=int(chat_id),
        message=post_for(message_id) if text is None else text,
        date=datetime(2026, 10, 24, 10, 17, 43, tzinfo=timezone.utc),
        document=None,
    )


def fake_enricher(base_url, username, password, rows, *, exclude_source):
    for row in rows:
        if row["code"] == "MIDE-307":
            row["cover_url"] = "https://img/mide307.jpg"
            row["images"] = json.dumps(["https://img/mide307.jpg"])
    return {"local": 1, "javdb": 0, "missing": 0}


def make_module(
    tmp_path: Path, importer, enricher=fake_enricher, exporter=None, deleter=None, record_deleter=None, **overrides
) -> MagnetImportModule:
    defaults = {"api_password": "secret", "channel_enabled": True, "channel_chat": CHANNEL, "channel_url_prefix": "https://t.me/example_channel", "channel_source_site": "sample", "channel_forum_id": "ExampleForum", "channel_forum_type": "ExampleForum", "channel_export_chat": "-1000000000002", "channel_export_source_site": "sample"}
    config = MagnetImportConfig(**{**defaults, **overrides})
    return MagnetImportModule(
        ModuleCard("magnet_import", "magnet", "", "automation", enabled=True),
        config,
        tmp_path,
        importer=importer,
        enricher=enricher,
        exporter=exporter or (lambda *args, **kwargs: ""),
        deleter=deleter or (lambda *args, **kwargs: 0),
        record_deleter=record_deleter or (lambda *args, **kwargs: 0),
    )


def history_of(messages):
    calls: list[int] = []

    async def reader(chat, *, min_id: int = 0):
        calls.append(min_id)
        for message in messages:
            if message.id > min_id:
                yield message

    reader.calls = calls
    return reader


def test_parse_post_extracts_code_title_links_and_size() -> None:
    post = parse_magnet_post(POST)
    assert post is not None
    assert post.code == "MIDE-307"
    assert post.title == "MIDE-307 奴隷人妻拍賣會 沖田杏梨"
    assert post.content == "這裡是有錢資產家們聚集的秘密俱樂部"
    assert post.links == [ED2K]
    assert format_size(post.size_bytes) == "8.15 GB"
    assert parse_magnet_post("纯文字没有链接") is None


def test_code_normalization_matches_magnetboard() -> None:
    assert extract_code("259LUXU-1835 ラグジュTV") == "LUXU-1835"
    assert extract_code("200GANA-3397 タイトル") == "GANA-3397"
    assert extract_code("FC2-PPV-4969013 タイトル") == "FC2PPV-4969013"
    assert extract_code("IPZZ-456(蓝光Remux)_restored") == "IPZZ-456"
    assert extract_code("www.98T.la@[LTX]ssni056.HD_restored.mp4", allow_compact=True) == "SSNI-056"
    assert extract_code("[myfans] 無題.mp4", allow_compact=True) == ""


def test_link_only_post_falls_back_to_file_name_and_keeps_multiple_links() -> None:
    post = parse_magnet_post("ed2k://|file|www.98T.la@390JAC-068_LTX.mp4|9099769089|4C311FEAE0C0EEE66F770C5A49ABCDEF|/")
    assert post is not None and post.code == "JAC-068"
    two = parse_magnet_post(
        "WAAA-192 标题\n\ned2k://|file|WAAA-192-LTX.mp4|1|6BBC5B2475993EA025FBCF07F68AA9D7|/\n\n"
        "magnet:?xt=urn:btih:c648167e0b621ce6d38892183f6381d3d5a4c76d"
    )
    assert two is not None and len(two.links) == 2


def test_config_parsing_for_channel_fields() -> None:
    parsed = magnet_import_config_from_dict({"channel_enabled": True, "channel_url_prefix": "https://t.me/x/", "channel_batch_size": 1})
    assert parsed.channel_enabled is True
    assert parsed.channel_url_prefix == "https://t.me/x"
    assert parsed.channel_batch_size == 10
    assert MagnetImportConfig().channel_enabled is False


def test_live_message_imports_one_row_with_mapped_fields(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer)

    async def run():
        result = await module.handle_message(SimpleNamespace(message=make_message(539, text=POST), chat_id=int(CHANNEL)))
        await module.wait_idle()
        return result

    result = asyncio.run(run())
    assert result.status == "handled"
    row = importer.rows[0][0]
    assert row["url"] == "https://t.me/example_channel/539"
    assert row["code"] == "MIDE-307"
    assert json.loads(row["magnets"]) == [ED2K]
    assert row["size"] == "8.15 GB"
    assert row["source_site"] == "sample"
    assert row["forum_type"] == "ExampleForum"
    assert row["magnet_hash"] == "ba2e92c0f1f9719532448eed72df6df2"  # momo 口径：文件 MD4
    assert row["published_at"] == "2026-10-24 18:17:43"
    assert row["id"] == "539"
    assert row["is_uncensored"] == "True"
    assert row["cover_url"] == "https://img/mide307.jpg"
    assert json.loads(row["images"]) == ["https://img/mide307.jpg"]
    assert module.card.metrics["channel"]["last_message_id"] == 539
    assert module.card.metrics["channel"]["imported"] == 1
    assert not list(tmp_path.joinpath("runtime/tmp/magnet_import").glob("*.csv"))


def test_channel_ignored_when_disabled_or_no_links(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer, channel_enabled=False)
    event = SimpleNamespace(message=make_message(1), chat_id=int(CHANNEL))
    assert asyncio.run(module.handle_message(event)).status == "ignored"
    module = make_module(tmp_path, importer)
    event = SimpleNamespace(message=make_message(2, text="公告"), chat_id=int(CHANNEL))
    assert asyncio.run(module.handle_message(event)).status == "ignored"
    assert importer.rows == []


def test_startup_catch_up_resumes_from_last_message_and_batches(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer, channel_batch_size=10)
    messages = [make_message(i) for i in range(1, 26)] + [make_message(26, text="无链接")]
    module.set_history_reader(history_of(messages))

    async def run(target):
        await target.start()
        await target.wait_idle()
        await target.stop()

    asyncio.run(run(module))
    assert [len(batch) for batch in importer.rows] == [10, 10, 5]
    assert module.card.metrics["channel"]["last_message_id"] == 25

    # 重启后只补拉 25 之后的消息
    importer2 = CsvImporter()
    reader = history_of(messages + [make_message(30)])
    restarted = make_module(tmp_path, importer2, channel_batch_size=10)
    restarted.set_history_reader(reader)
    asyncio.run(run(restarted))
    assert reader.calls == [25]
    assert [row["url"] for row in importer2.rows[0]] == ["https://t.me/example_channel/30"]


def test_full_scan_starts_from_zero_and_failed_live_import_is_retried(tmp_path: Path) -> None:
    failing = CsvImporter(error=RuntimeError("down"))
    module = make_module(tmp_path, failing)
    module.channel.state.update(chat=CHANNEL, last_message_id=50)

    async def live():
        await module.handle_message(SimpleNamespace(message=make_message(51), chat_id=int(CHANNEL)))
        await module.wait_idle()

    asyncio.run(live())
    assert module.card.metrics["channel"]["last"]["status"] == "failed"
    assert module.channel.state["pending_from"] == 51

    importer = CsvImporter()
    module.channel._importer = importer
    reader = history_of([make_message(i) for i in (10, 51)])
    module.set_history_reader(reader)

    async def scan(full):
        module._running = True
        assert module.request_channel_scan(full=full)
        await module.wait_idle()

    asyncio.run(scan(False))
    assert reader.calls == [50]
    assert "pending_from" not in module.channel.state
    asyncio.run(scan(True))
    assert reader.calls == [50, 0]
    assert module.card.metrics["channel"]["last"]["status"] == "imported"
    assert module.card.metrics["channel"]["scanning"] is False


def test_uncensored_markers() -> None:
    def flag(name: str) -> bool:
        post = parse_magnet_post(f"ABC-123 标题\n\ned2k://|file|{name}|1|BA2E92C0F1F9719532448EED72DF6DF2|/")
        assert post is not None
        return post.is_uncensored

    assert flag("www.98T.la@mide307_restored.mp4")
    assert flag("midv-887_restore.mp4")
    assert flag("SONE-054_LTX.mp4")
    assert flag("MIDA-824-U.mp4")
    assert flag("IPX-750_PJ.mp4")
    assert flag("IPZZ-081C(破解版)-有水印.mp4")
    assert not flag("WSA-001_wm.mp4")
    assert not flag("SOE-691-R.mp4")
    assert not flag("START-640.mp4")
    assert not flag("UNKO-001.mp4")


def test_enrichment_failure_still_imports(tmp_path: Path) -> None:
    def broken(*args, **kwargs):
        raise ConnectionError("javdb down")

    importer = CsvImporter()
    module = make_module(tmp_path, importer, enricher=broken)

    async def run():
        await module.handle_message(SimpleNamespace(message=make_message(7), chat_id=int(CHANNEL)))
        await module.wait_idle()

    asyncio.run(run())
    assert importer.rows[0][0]["images"] == "[]"


def test_rebuild_deletes_source_then_reimports_from_start(tmp_path: Path) -> None:
    events: list[str] = []

    def deleter(base_url, username, password, *, source_site, url_prefix):
        events.append(f"delete:{source_site}:{url_prefix}")
        return 3

    class OrderedImporter(CsvImporter):
        def __call__(self, *args, **kwargs):
            events.append("import")
            return super().__call__(*args, **kwargs)

    importer = OrderedImporter()
    module = make_module(tmp_path, importer, deleter=deleter)
    module.channel.state.update(chat=CHANNEL, last_message_id=99)
    reader = history_of([make_message(1), make_message(2)])
    module.set_history_reader(reader)

    async def run():
        module._running = True
        assert module.request_channel_scan(full=False, rebuild=True)
        await module.wait_idle()

    asyncio.run(run())
    assert events == ["delete:sample:https://t.me/example_channel/", "import"]
    assert reader.calls == [0]
    assert module.card.metrics["channel"]["imported"] == 2
    assert "全量重建完成" in module.card.metrics["channel"]["last"]["detail"]


def test_rebuild_failure_keeps_error_and_does_not_import(tmp_path: Path) -> None:
    def deleter(*args, **kwargs):
        raise RuntimeError("delete refused")

    importer = CsvImporter()
    module = make_module(tmp_path, importer, deleter=deleter)
    module.set_history_reader(history_of([make_message(1)]))

    async def run():
        module._running = True
        module.request_channel_scan(full=True, rebuild=True)
        await module.wait_idle()

    asyncio.run(run())
    assert importer.rows == []
    assert module.card.metrics["channel"]["last"]["status"] == "failed"


EXPORT_CSV = (
    ",".join(CSV_COLUMNS)
    + "\n"
    + "\n".join(
        ",".join({"id": str(rid), "magnet_hash": f"h{rid}", "source_site": site, "title": f"T{rid}"}.get(col, "") for col in CSV_COLUMNS)
        for rid, site in ((120, "sample"), (50, "sample"), (300, "sample"), (999, "xjasna"))
    )
    + "\n"
)


def test_select_source_rows_sorted_by_record_id() -> None:
    fields, rows = select_source_rows(EXPORT_CSV, "sample")
    assert fields == CSV_COLUMNS
    assert [rid for rid, _ in rows] == [50, 120, 300]


def test_export_is_full_and_scheduled_run_skips_without_new_records(tmp_path: Path) -> None:
    sent: list[tuple[str, str, str]] = []
    export_text = [EXPORT_CSV]

    async def sender(chat, path, caption):
        sent.append((chat, Path(path).read_text(encoding="utf-8"), caption))

    module = make_module(tmp_path, CsvImporter(), exporter=lambda *args, **kwargs: export_text[0])
    module.set_file_sender(sender)
    job = module.export_job

    async def run():
        module._running = True
        manual = await module.run_channel_export()  # 后台按钮：总是发全量
        scheduled_same = await job.run_once()  # 定时：没有新记录 → 不发
        manual_again = await module.run_channel_export()  # 按钮：仍然发全量
        export_text[0] = EXPORT_CSV + ",".join(
            {"id": "400", "source_site": "sample", "title": "T400"}.get(col, "") for col in CSV_COLUMNS
        ) + "\n"
        scheduled_new = await job.run_once()  # 定时：有新记录 → 发全量
        return manual, scheduled_same, manual_again, scheduled_new

    manual, scheduled_same, manual_again, scheduled_new = asyncio.run(run())
    assert [manual["status"], scheduled_same["status"], manual_again["status"], scheduled_new["status"]] == [
        "sent", "empty", "sent", "sent"
    ]
    assert len(sent) == 3
    chat, content, caption = sent[0]
    assert chat == "-1000000000002"
    assert content.count("\n") == 4  # 表头 + 3 条 ltx，xjasna 不导出
    assert caption.startswith("sample 全量 3 条（本次新增 3 条）")
    assert sent[1][2].startswith("sample 全量 3 条（本次新增 0 条）")
    assert sent[2][1].count("\n") == 5 and sent[2][2].startswith("sample 全量 4 条（本次新增 1 条）")
    assert module.card.metrics["channel_export"]["last_record_id"] == 400
    assert not list((tmp_path / "runtime/tmp/magnet_import").glob("*.csv"))


def test_export_due_slot_window(tmp_path: Path) -> None:
    from datetime import timedelta as td

    tz = timezone(td(hours=8))
    module = make_module(tmp_path, CsvImporter(), channel_export_enabled=True)
    job = module.export_job
    friday_noon = datetime(2026, 10, 30, 12, 0, 20, tzinfo=tz)
    assert job.due_slot(friday_noon) == "2026-10-30 12:00"
    assert job.due_slot(friday_noon + td(minutes=20)) is None
    assert job.due_slot(friday_noon - td(days=1)) is None
    job.state["last_slot"] = "2026-10-30 12:00"
    assert job.due_slot(friday_noon) is None
    module.config.channel_export_enabled = False
    job.state.pop("last_slot")
    assert job.due_slot(friday_noon) is None


def export_text(records: list[tuple[int, int, str]]) -> str:
    """records: (库内 id, 消息 id, 文件 hash)。"""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record_id, message_id, file_hash in records:
        writer.writerow({
            "id": record_id,
            "source_site": "sample",
            "url": f"https://t.me/example_channel/{message_id}",
            "magnet_hash": file_hash.lower(),
            "magnets": json.dumps([f"ed2k://|file|a.mp4|1|{file_hash}|/"]),
        })
    return out.getvalue()


def test_parse_strips_leading_symbol_and_collects_hashes() -> None:
    post = parse_magnet_post(
        "🔗 SONE-164\n\ned2k://|file| www.98T.la@SONE-164_wm.mp4 |7368231925|C0DBC9CB04BD857852978A778F7669D6|/"
    )
    assert post is not None
    assert post.title == "SONE-164" and post.code == "SONE-164"
    assert post.link_hashes == ["ed2k:c0dbc9cb04bd857852978a778f7669d6"]


def test_live_repost_of_same_file_is_skipped_keeping_earliest(tmp_path: Path) -> None:
    importer = CsvImporter()
    existing = export_text([(900, 600, "C0DBC9CB04BD857852978A778F7669D6")])
    module = make_module(tmp_path, importer, exporter=lambda *a, **k: existing)
    repost = "🔗 SONE-164\n\ned2k://|file|x.mp4|1|c0dbc9cb04bd857852978a778f7669d6|/"

    async def run():
        await module.handle_message(SimpleNamespace(message=make_message(603, text=repost), chat_id=int(CHANNEL)))
        await module.wait_idle()
        # 同一文件在新消息里第二次出现也拦下，不同文件正常导入
        await module.handle_message(SimpleNamespace(message=make_message(604), chat_id=int(CHANNEL)))
        await module.wait_idle()
        await module.handle_message(SimpleNamespace(message=make_message(605, text=post_for(604)), chat_id=int(CHANNEL)))
        await module.wait_idle()

    asyncio.run(run())
    assert [row["url"] for batch in importer.rows for row in batch] == ["https://t.me/example_channel/604"]
    last = module.card.metrics["channel"]["last"]
    assert last["status"] == "skipped" and "#604" in last["detail"]
    assert module.card.metrics["channel"]["last_message_id"] == 605


def test_index_build_removes_existing_later_duplicates(tmp_path: Path) -> None:
    deleted: list[list[int]] = []
    existing = export_text([
        (10, 12, "A" * 32),
        (20, 314, "a" * 32),  # 与 #12 同文件，删
        (30, 600, "B" * 32),
        (40, 603, "B" * 32),  # 删
        (50, 601, "B" * 32),  # 删
        (60, 700, "C" * 32),
    ])
    module = make_module(
        tmp_path,
        CsvImporter(),
        exporter=lambda *a, **k: existing,
        record_deleter=lambda base, user, pw, ids: deleted.append(sorted(ids)) or len(ids),
    )
    index = asyncio.run(module.channel._ensure_index())
    assert deleted == [[20, 40, 50]]
    assert index["ed2k:" + "a" * 32] == 12 and index["ed2k:" + "b" * 32] == 600


def test_scan_batch_drops_duplicates_within_and_against_index(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer, exporter=lambda *a, **k: export_text([(1, 5, f"{5:032X}")]))
    module.set_history_reader(history_of([make_message(5), make_message(6), make_message(7, text=post_for(6))]))

    async def run():
        module._running = True
        assert module.request_channel_scan(full=True)
        await module.wait_idle()

    asyncio.run(run())
    assert [row["url"] for row in importer.rows[0]] == ["https://t.me/example_channel/5", "https://t.me/example_channel/6"]
    assert "重复帖 1" in module.card.metrics["channel"]["last"]["detail"]


LTX_POST = (
    "🎬 結婚前夜。無法忍耐初戀對象前女友巨乳誘惑 小花暖\n\n"
    "#LTX #PPPE-087 #自制 #4K #60FPS\n"
    "ed2k://|file|PPPE-087_LTX_4K.mp4|26820463637|5A7159DF6B83851AA886460FBE0BDF3F|/\n"
    "#发布_20261104_215742"
)


def test_parse_example_channel_post_takes_code_and_tags_from_hashtags() -> None:
    post = parse_magnet_post(LTX_POST)
    assert post is not None
    assert post.code == "PPPE-087"
    assert post.title == "結婚前夜。無法忍耐初戀對象前女友巨乳誘惑 小花暖"
    assert post.content == ""
    assert post.tags == ["自制", "4K", "60FPS"]
    assert post.is_uncensored is True
    # 旧版帖子标题带番号前缀、标点开头：去掉番号，保留「
    old = parse_magnet_post(
        "MIDA-837 「何でもしてアゲル」 石川澪\n\n#LTX #MIDA-837 #98T\n"
        "ed2k://|file|98T@MIDA-837-U_LTX.mp4|7418417758|4214FE4E5B36D9B6AE4D7B6B9059FB58|h=57CVJC63KAZVVUR6SESYOK5D7K7CG24L|/"
    )
    assert old.code == "MIDA-837" and old.title == "「何でもしてアゲル」 石川澪" and old.tags == ["98T"]


def test_example_channel_row_writes_tags_and_forum_name(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer)

    async def run():
        await module.handle_message(SimpleNamespace(message=make_message(2066, text=LTX_POST), chat_id=int(CHANNEL)))
        await module.wait_idle()

    asyncio.run(run())
    row = importer.rows[0][0]
    assert row["url"] == "https://t.me/example_channel/2066"
    assert row["source_site"] == "sample" and row["magnet_hash"] == "5a7159df6b83851aa886460fbe0bdf3f"
    assert json.loads(row["tags"]) == ["自制", "4K", "60FPS"]
    assert row["forum_name"] == "ExampleForum"


def test_posts_matching_avdb_records_are_skipped_but_not_deleted(tmp_path: Path) -> None:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record_id, magnet_hash, file_hash in ((5, "", "A" * 32), (6, "", "A" * 32), (7, "https://t.me/example_channel/9", "A" * 32)):
        writer.writerow({
            "id": record_id, "source_site": "sample", "url": magnet_hash,
            "magnets": json.dumps([f"ed2k://|file|a.mp4|1|{file_hash}|/"]),
        })
    deleted: list[list[int]] = []
    importer = CsvImporter()
    module = make_module(
        tmp_path,
        importer,
        exporter=lambda *a, **k: out.getvalue(),
        record_deleter=lambda base, user, pw, ids: deleted.append(sorted(ids)) or len(ids),
    )
    dup = "🎬 标题\n\n#LTX #ABC-123 #98T\ned2k://|file|x.mp4|1|" + "a" * 32 + "|/"

    async def run():
        await module.handle_message(SimpleNamespace(message=make_message(20, text=dup), chat_id=int(CHANNEL)))
        await module.wait_idle()

    asyncio.run(run())
    assert importer.rows == []
    assert deleted == [[7]]  # 只删与 AVDB 重复的频道记录，AVDB 记录（含其内部重复）不动
    last = module.card.metrics["channel"]["last"]
    assert last["status"] == "skipped" and "库内已有记录" in last["detail"]


def test_channel_change_resets_progress(tmp_path: Path) -> None:
    importer = CsvImporter()
    module = make_module(tmp_path, importer)
    module.channel.state.update(last_message_id=752, imported=637)  # 旧频道的进度（未记录 chat）
    reader = history_of([make_message(1), make_message(2)])
    module.set_history_reader(reader)

    async def run():
        await module.start()
        await module.wait_idle()
        await module.stop()

    asyncio.run(run())
    assert reader.calls == [0]
    assert module.channel.state["chat"] == CHANNEL
    assert module.card.metrics["channel"]["last_message_id"] == 2


def test_primary_file_hash_prefers_ed2k_md4_then_btih() -> None:
    from telegram_bot.shared.magnet_post_parser import normalize_magnet_hash, primary_file_hash

    ed2k = "ed2k://|file|a.mp4|1|21DB87E17D6EF61BA223DAFA8CEF69D8|/"
    magnet = "magnet:?xt=urn:btih:CE30094BD2CF37D12BD5A4A660256DB0B3936A92&dn=x"
    assert primary_file_hash(f"{magnet}\n{ed2k}") == "21db87e17d6ef61ba223dafa8cef69d8"
    assert primary_file_hash(magnet) == "ce30094bd2cf37d12bd5a4a660256db0b3936a92"
    assert primary_file_hash("") == ""
    row = {"source_site": "sample", "magnet_hash": "ltx-1", "magnets": json.dumps([ed2k])}
    assert normalize_magnet_hash(row, {"sample"}) and row["magnet_hash"] == "21db87e17d6ef61ba223dafa8cef69d8"
    other = {"source_site": "sehuatang", "magnet_hash": "1", "magnets": json.dumps([ed2k])}
    assert not normalize_magnet_hash(other, {"sample"}) and other["magnet_hash"] == "1"


def test_export_rewrites_legacy_magnet_hash(tmp_path: Path) -> None:
    sent: list[str] = []
    text = ",".join(CSV_COLUMNS) + "\n" + ",".join(
        {"id": "1", "source_site": "sample", "title": "T", "magnet_hash": "ltx-2085",
         "magnets": '"[""ed2k://|file|a.mp4|1|21DB87E17D6EF61BA223DAFA8CEF69D8|/""]"'}.get(col, "")
        for col in CSV_COLUMNS
    ) + "\n"

    async def sender(chat, path, caption):
        sent.append(Path(path).read_text(encoding="utf-8"))

    module = make_module(tmp_path, CsvImporter(), exporter=lambda *a, **k: text)
    module.set_file_sender(sender)

    async def run():
        module._running = True
        await module.run_channel_export()

    asyncio.run(run())
    row = next(csv.DictReader(io.StringIO(sent[0])))
    assert row["magnet_hash"] == "21db87e17d6ef61ba223dafa8cef69d8"
