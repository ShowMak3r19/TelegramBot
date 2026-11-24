from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.config import AppConfig, MagnetImportConfig, magnet_import_config_from_dict
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.magnet_import import MagnetImportModule
from telegram_bot.shared.telegram_download import download_document_resumable

CHAT_ID = -1000000000002
CONTENT = (
    'id,title,magnets,url,content\n'
    f'1,Sample,"[""magnet:?xt=urn:btih:{"A" * 40}""]",https://example.com/1,' + "x" * 3000 + "\n"
).encode("utf-8")


class FakeClient:
    def __init__(self, content: bytes = CONTENT, fail_after: int | None = None) -> None:
        self.content = content
        self.fail_after = fail_after
        self.offsets: list[int] = []
        self.sent: list[dict[str, object]] = []
        self.refetched = 0

    async def iter_download(self, media: object, *, offset: int = 0, request_size: int = 1024, file_size: int | None = None):
        self.offsets.append(offset)
        position = offset
        while position < len(self.content):
            if self.fail_after is not None and position >= self.fail_after:
                self.fail_after = None
                raise ConnectionError("network dropped")
            yield self.content[position : position + request_size]
            position += request_size

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})

    async def get_messages(self, chat_id: int, ids: int) -> object:
        self.refetched += 1
        return None


class FakeImporter:
    def __init__(self, error: Exception | None = None, result: dict | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error
        self.result = result or {"success": True, "data": {"imported": 10, "skipped": 2}}

    def __call__(self, base_url, username, password, file_path, file_name, **kwargs):
        self.calls.append(
            {"base_url": base_url, "username": username, "password": password, "name": file_name,
             "content": Path(file_path).read_bytes(), **kwargs}
        )
        if self.error:
            raise self.error
        return self.result


def make_message(*, name="x1080x_all_2026-10-09.csv", username="example_sender", chat_id=CHAT_ID, message_id=7, size=None):
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender_id=123,
        sender=SimpleNamespace(username=username),
        document=SimpleNamespace(size=size if size is not None else len(CONTENT)),
        file=SimpleNamespace(name=name, size=size if size is not None else len(CONTENT)),
    )


def make_module(tmp_path: Path, importer=None, posts_importer=None, **overrides) -> MagnetImportModule:
    overrides.setdefault("watch_chats", [str(CHAT_ID)])
    overrides.setdefault("sender_usernames", ["example_sender"])
    overrides.setdefault("channel_source_site", "sample")
    config = MagnetImportConfig(api_password="secret", **overrides)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    module = MagnetImportModule(
        ModuleCard("magnet_import", "magnet", "", "automation", enabled=True),
        config,
        tmp_path,
        importer=importer or FakeImporter(),
        posts_importer=posts_importer or FakeImporter(),
        sleep=fake_sleep,
    )
    module.sleeps = sleeps
    return module


async def _dispatch(module: MagnetImportModule, message, client):
    result = await module.handle_message(SimpleNamespace(message=message, chat_id=message.chat_id, client=client))
    await module.wait_idle()
    return result


def test_config_defaults_and_parsing() -> None:
    config = AppConfig.from_dict(AppConfig.defaults_dict())
    assert config.magnet_import.watch_chats == []
    assert config.magnet_import.sender_usernames == []
    assert config.modules.magnet_import is False
    assert config.magnet_import.file_name_pattern == r"^x1080x.*\.csv$"

    parsed = magnet_import_config_from_dict({"sender_usernames": ["@Foo"], "download_retries": 99, "api_base_url": "http://a/"})
    assert parsed.sender_usernames == ["Foo"]
    assert parsed.download_retries == 20
    assert parsed.api_base_url == "http://a"


def test_password_is_masked_and_preserved(tmp_path: Path) -> None:
    module = make_module(tmp_path)
    assert module.card.config["api_password"] == ""
    assert module.card.config["has_api_password"] is True

    module.update_config({"api_password": "", "reply_text": "ok"})
    assert module.config.api_password == "secret"
    assert module.config.reply_text == "ok"
    module.update_config({"api_password": "new"})
    assert module.config.api_password == "new"

    app = AppConfig()
    app.magnet_import.api_password = "secret"
    assert app.public_dict()["magnet_import"]["api_password"] != "secret"


def test_imports_csv_replies_and_cleans_up(tmp_path: Path) -> None:
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    client = FakeClient()

    result = asyncio.run(_dispatch(module, make_message(), client))

    assert result.status == "handled"
    assert len(importer.calls) == 1
    call = importer.calls[0]
    rows = list(_csv.DictReader(_io.StringIO(call["content"].decode("utf-8"))))
    assert len(rows) == 1 and rows[0]["title"] == "Sample" and rows[0]["url"] == "https://example.com/1"
    assert call["password"] == "secret"
    assert call["update_existing"] is False and call["skip_duplicates"] is True
    assert client.sent == [{"chat_id": CHAT_ID, "text": "已自动导入，谢谢老大", "reply_to": 7}]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []
    state = json.loads((tmp_path / "runtime/data/magnet_import_state.json").read_text(encoding="utf-8"))
    assert state["processed"][f"{CHAT_ID}:7"]["status"] == "imported"
    assert module.card.metrics["imported"] == 1

    # 同一消息（编辑或重复事件）不会再次导入
    asyncio.run(_dispatch(module, make_message(), client))
    assert len(importer.calls) == 1


def test_state_survives_restart(tmp_path: Path) -> None:
    asyncio.run(_dispatch(make_module(tmp_path), make_message(), FakeClient()))
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    result = asyncio.run(_dispatch(module, make_message(), FakeClient()))
    assert result.status == "ignored"
    assert importer.calls == []


def test_ignores_unmatched_messages(tmp_path: Path) -> None:
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    client = FakeClient()
    for message in (
        make_message(username="someone"),
        make_message(chat_id=-100999),
        make_message(name="notes.txt"),
        make_message(name="other_all_2026-10-09.csv"),
        make_message(name="backup_x1080x_2026-10-09.csv"),
        make_message(name="x1080x_all_2026-10-09.txt"),
    ):
        assert asyncio.run(_dispatch(module, message, client)).status == "ignored"
    no_doc = make_message()
    no_doc.document = None
    assert asyncio.run(_dispatch(module, no_doc, client)).status == "ignored"
    assert importer.calls == []


def test_import_failure_does_not_reply_and_cleans_up(tmp_path: Path) -> None:
    importer = FakeImporter(RuntimeError("登录失败"))
    module = make_module(tmp_path, importer)
    client = FakeClient()

    asyncio.run(_dispatch(module, make_message(), client))

    assert client.sent == []
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []
    assert module.card.metrics["last"]["status"] == "failed"
    assert "登录失败" in module.card.metrics["last"]["detail"]


def test_missing_credentials_skip_download(tmp_path: Path) -> None:
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    module.config.api_password = ""
    client = FakeClient()
    asyncio.run(_dispatch(module, make_message(), client))
    assert client.offsets == [] and importer.calls == []


def test_download_resumes_after_failure(tmp_path: Path) -> None:
    client = FakeClient(fail_after=2048)
    message = make_message()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def refetch():
        return await client.get_messages(CHAT_ID, ids=7)

    dest = tmp_path / "out.csv"
    size = asyncio.run(
        download_document_resumable(client, message, dest, retries=3, refetch=refetch, sleep=fake_sleep, request_size=1024)
    )
    assert size == len(CONTENT)
    assert dest.read_bytes() == CONTENT
    assert client.offsets == [0, 2048]
    assert client.refetched == 1 and len(sleeps) == 1
    assert not (tmp_path / "out.csv.part").exists()


def test_download_rejects_size_mismatch(tmp_path: Path) -> None:
    async def noop(_):
        return None

    client = FakeClient()
    message = make_message(size=len(CONTENT) + 10)
    try:
        asyncio.run(download_document_resumable(client, message, tmp_path / "x.csv", retries=2, sleep=noop, request_size=1024))
    except IOError as exc:
        assert "下载不完整" in str(exc)
    else:
        raise AssertionError("size mismatch should fail")


# ---- 手动 /import ----

import csv as _csv
import io as _io

from telegram_bot.shared.magnet_csv import CsvFormatError, normalize_import_csv

BTIH_A = "magnet:?xt=urn:btih:" + "A" * 40
BTIH_B = "magnet:?xt=urn:btih:" + "B" * 40
ED2K_C = "ed2k://|file|C.mp4|100|" + "C" * 32 + "|/"


def _csv_bytes(header: list[str], rows: list[list[str]], bom: bool = False) -> bytes:
    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(_csv.DictReader(fh))


class FakeCommand(SimpleNamespace):
    async def get_reply_message(self):
        return self.replied

    async def delete(self):
        self.deleted = True

    async def edit(self, text, **kwargs):
        if self.edit_fails:
            raise RuntimeError("edit failed")
        self.edits.append(text)


def _command(replied, text="/import", out=True, edit_fails=False):
    return FakeCommand(id=99, chat_id=CHAT_ID, out=out, raw_text=text, is_reply=replied is not None,
                       replied=replied, deleted=False, edits=[], edit_fails=edit_fails)


def test_normalize_strips_bom_fixes_rows_and_dedupes(tmp_path: Path) -> None:
    src, dest = tmp_path / "in.csv", tmp_path / "out.csv"
    header = ["title", "magnets", "url", "source_site", "forum_name", "weird_col"]
    rows = [
        ["A", json.dumps([BTIH_A]), "https://x/1", "sehuatang", "Forum", "z"],
        ["A again", json.dumps([BTIH_A]), "https://x/2", "sehuatang", "F", "z"],  # 同磁力不同帖子：保留
        ["B", BTIH_B, "https://x/1", "sehuatang", "F", "z"],  # 同 url：重复
        ["C", ED2K_C, "", "ltx", "F", "z"],  # 裸链接 → JSON
        ["C2", ED2K_C, "", "ltx", "F", "z"],  # 无 url 时同文件：重复
        ["", json.dumps([BTIH_B]), "https://x/3", "sehuatang", "F", "z"],  # 缺标题
        ["D", "[broken", "https://x/4", "sehuatang", "F", "z"],  # 磁力格式错误
        ["E", "", "", "ltx", "F", "z"],  # 无链接
        ["F", "[]"],  # 列数不符
        ["", "", "", "", "", ""],  # 空行，不计数
    ]
    src.write_bytes(_csv_bytes(header, rows, bom=True))

    result = normalize_import_csv(src, dest)

    assert (result.total, result.written, result.duplicates) == (9, 3, 2)
    assert dict(result.bad) == {"title": 1, "magnets": 1, "no_link": 1, "columns": 1}
    assert result.unknown_columns == ["weird_col"]
    assert not dest.read_bytes().startswith(b"\xef\xbb\xbf")
    out = _read_rows(dest)
    assert [row["title"] for row in out] == ["A", "A again", "C"]
    assert json.loads(out[2]["magnets"]) == [ED2K_C]
    assert out[0]["forum_name"] == "Forum"  # 新版导出列原样保留
    assert all(row["id"] for row in out)
    assert out[0]["is_downloaded"] == "False"  # 缺失列用默认值
    assert "weird_col" not in out[0]


def test_normalize_rejects_bad_header(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    for header in (["title", "url"], ["title", "magnets"], ["name", "magnets", "url"]):
        src.write_bytes(_csv_bytes(header, [["x"] * len(header)]))
        try:
            normalize_import_csv(src, tmp_path / "out.csv")
        except CsvFormatError as exc:
            assert "缺少必需列" in str(exc)
        else:
            raise AssertionError(f"header {header} should be rejected")
    src.write_bytes("title,magnets,url\n".encode("gbk") + "中文,[],u\n".encode("gbk"))
    try:
        normalize_import_csv(src, tmp_path / "out.csv")
    except CsvFormatError as exc:
        assert "UTF-8" in str(exc)
    else:
        raise AssertionError("non-utf8 should be rejected")


def test_import_command_checks_imports_and_replies(tmp_path: Path) -> None:
    content = _csv_bytes(
        ["title", "magnets", "url"],
        [["A", json.dumps([BTIH_A]), "u1"], ["A2", json.dumps([BTIH_A]), "u1"], ["B", json.dumps([BTIH_B]), "u3"]],
    )
    importer = FakeImporter(result={"success": True, "data": {"imported_records": 1, "skipped_records": 1, "error_records": 0}})
    calls = importer.calls
    module = make_module(tmp_path, importer)
    replied = make_message(name="anything.CSV", username="someone", message_id=50, size=len(content))
    client = FakeClient(content)
    command = _command(replied)

    result = asyncio.run(_dispatch(module, command, client))

    assert result.status == "handled"
    assert command.deleted is False
    assert command.edits[0].startswith("⏳ 正在导入 anything.CSV")
    assert any("下载中" in t for t in command.edits) and any("上传到 MagnetBoard" in t for t in command.edits)
    assert client.sent == []  # 结果原地编辑进 /import 消息，不另发
    assert len(calls) == 1 and calls[0]["skip_duplicates"] is True
    rows = list(_csv.DictReader(_io.StringIO(calls[0]["content"].decode("utf-8"))))
    assert [row["title"] for row in rows] == ["A", "B"]
    final = command.edits[-1]
    assert final.startswith("✅ 已导入 anything.CSV")
    assert "文件内重复 1 行" in final and "新增 1，跳过 1，错误 0" in final
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []

    # 同一文件可以再次手动导入（重复由 MagnetBoard 跳过）
    asyncio.run(_dispatch(module, _command(replied), client))
    assert len(calls) == 2

    # 编辑失败时退回为回复 CSV 另发结果
    fallback = _command(replied, edit_fails=True)
    asyncio.run(_dispatch(module, fallback, client))
    assert client.sent[-1]["reply_to"] == 50 and client.sent[-1]["text"].startswith("✅ 已导入 anything.CSV")


def test_import_command_rejects_bad_targets(tmp_path: Path) -> None:
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    client = FakeClient()

    for replied in (None, make_message(name="notes.txt")):
        command = _command(replied)
        assert asyncio.run(_dispatch(module, command, client)).status == "handled"
        assert command.deleted is False
        assert command.edits[-1].startswith("❌ 请回复一个 .csv 文件")
    assert client.sent == []

    # 别人发的 /import 不处理；也不会被当作自动导入
    other = _command(make_message(name="a.csv"), out=False)
    assert asyncio.run(_dispatch(module, other, client)).status == "ignored"
    assert other.deleted is False
    assert importer.calls == [] and client.offsets == []


def test_import_command_format_error_replies_without_import(tmp_path: Path) -> None:
    content = _csv_bytes(["foo", "bar"], [["1", "2"]])
    importer = FakeImporter()
    module = make_module(tmp_path, importer)
    client = FakeClient(content)

    command = _command(make_message(name="a.csv", size=len(content)))
    asyncio.run(_dispatch(module, command, client))

    assert importer.calls == []
    assert "格式校对未通过" in command.edits[-1]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []


def test_normalize_rewrites_magnet_hash_to_md4_for_hash_sources(tmp_path: Path) -> None:
    """第三方 LTX 清单常把 magnet_hash 填成消息号/资源编号；按 momo 口径改为文件 MD4，其他来源不动。"""
    src = tmp_path / "ltx.csv"
    out = _io.StringIO()
    writer = _csv.DictWriter(out, fieldnames=["title", "url", "magnets", "magnet_hash", "source_site"])
    writer.writeheader()
    ed2k = "ed2k://|file|DLDSS-538_LTX.mp4|4911871979|21DB87E17D6EF61BA223DAFA8CEF69D8|/"
    writer.writerow({"title": "a", "url": "https://t.me/example_channel/2085", "magnets": json.dumps([ed2k]),
                     "magnet_hash": "ltx-2085", "source_site": "ltx"})
    writer.writerow({"title": "b", "url": "", "magnets": json.dumps([ed2k]),
                     "magnet_hash": "5236898717068280", "source_site": "ltx"})
    writer.writerow({"title": "c", "url": "https://x/1", "magnets": json.dumps([ed2k]),
                     "magnet_hash": "1076824", "source_site": "agaghhh"})
    src.write_text(out.getvalue(), encoding="utf-8")
    dest = tmp_path / "clean.csv"
    result = normalize_import_csv(src, dest, frozenset({"ltx"}))
    rows = list(_csv.DictReader(dest.open(encoding="utf-8")))
    assert [row["magnet_hash"] for row in rows] == ["21db87e17d6ef61ba223dafa8cef69d8"] * 2 + ["1076824"]
    assert result.rehashed == 2 and "改为文件 MD4 2 行" in result.describe()
    # 不传来源时保持原样
    normalize_import_csv(src, dest)
    assert [row["magnet_hash"] for row in _csv.DictReader(dest.open(encoding="utf-8"))][0] == "ltx-2085"


def test_auto_import_normalizes_ltx_csv_and_matches_combined_pattern(tmp_path: Path) -> None:
    ed2k = "ed2k://|file|DLDSS-538_LTX.mp4|4911871979|21DB87E17D6EF61BA223DAFA8CEF69D8|/"
    raw = _csv_bytes(
        ["title", "url", "magnets", "magnet_hash", "source_site"],
        [
            ["Item 1", "", json.dumps([ed2k]), "5236898717068280", "sample"],
            ["Item 1 dup", "", json.dumps([ed2k]), "5236898717068280", "sample"],
        ],
        bom=True,
    )
    importer = FakeImporter()
    module = make_module(
        tmp_path,
        importer,
        sender_usernames=["example_sender", "sender_b"],
        file_name_pattern=r"^(?:x1080x.*|LTX-\d+)\.csv$",
    )
    client = FakeClient(raw)

    # 不匹配的文件名仍被忽略
    for bad_name in ("ltx_2026-11-06.csv", "LTX-abc.csv", "LTX-6099.txt", "prefix_LTX-6099.csv"):
        msg = make_message(name=bad_name, username="sender_b", message_id=200, size=len(raw))
        assert asyncio.run(_dispatch(module, msg, client)).status == "ignored"
    assert importer.calls == []

    # 匹配 LTX-<数字>.csv 且发送者在监控名单中：自动校对、去重并改写 ltx magnet_hash 为文件 MD4
    ok_msg = make_message(name="LTX-6099.csv", username="sender_b", message_id=201, size=len(raw))
    assert asyncio.run(_dispatch(module, ok_msg, client)).status == "handled"
    assert len(importer.calls) == 1
    uploaded = importer.calls[0]["content"]
    assert not uploaded.startswith(b"\xef\xbb\xbf")
    rows = list(_csv.DictReader(_io.StringIO(uploaded.decode("utf-8"))))
    assert len(rows) == 1
    assert rows[0]["magnet_hash"] == "21db87e17d6ef61ba223dafa8cef69d8"
    assert rows[0]["id"] == "1"
    assert client.sent == [{"chat_id": CHAT_ID, "text": "已自动导入，谢谢老大", "reply_to": 201}]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []


def test_auto_import_rejects_bad_csv_without_reply_or_upload(tmp_path: Path) -> None:
    importer = FakeImporter()
    module = make_module(tmp_path, importer)

    # 缺少必需列
    bad_header = _csv_bytes(["foo", "bar"], [["1", "2"]])
    client = FakeClient(bad_header)
    asyncio.run(_dispatch(module, make_message(message_id=301, size=len(bad_header)), client))
    assert importer.calls == [] and client.sent == []
    assert module.card.metrics["last"]["status"] == "failed"
    assert "格式校对未通过" in module.card.metrics["last"]["detail"]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []

    # 表头合法但没有有效行
    empty_valid = _csv_bytes(["title", "magnets", "url"], [["", "[]", ""]])
    client = FakeClient(empty_valid)
    asyncio.run(_dispatch(module, make_message(message_id=302, size=len(empty_valid)), client))
    assert importer.calls == [] and client.sent == []
    assert module.card.metrics["last"]["status"] == "failed"
    assert "没有可导入的行" in module.card.metrics["last"]["detail"]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []


# ---- 色花综合帖子 CSV（/api/posts/import）----

from telegram_bot.shared.magnetboard_api import POST_CSV_COLUMNS, import_posts_csv_sync


def test_normalize_posts_csv_aligns_20_columns_dedupes_and_skips_ltx_rehash(tmp_path: Path) -> None:
    """旧版/乱序/含 BOM 的色花综合帖子 CSV 标准化为精确 20 列，按 tid 优先、original_url 兜底去重。"""
    src, dest = tmp_path / "posts_in.csv", tmp_path / "posts_out.csv"
    # 模拟旧版导出：缺少 is_downloaded/images/attachments，列顺序不同，带额外未知列
    header = ["board_name", "title", "original_url", "tid", "magnet_link", "extra_col"]
    rows = [
        ["综合讨论区", "无磁力纯图帖", "https://example.com/thread-1001-1-1.html", "1001", "", "x"],
        ["综合讨论区", "同 tid 重复", "https://example.com/thread-1001-2-1.html", "1001", "", "x"],
        ["综合讨论区", "多行 ed2k 帖", "https://example.com/thread-1002-1-1.html", "1002", f"{ED2K_C}\n{BTIH_A}", "x"],
        ["综合讨论区", "无 tid 按链接去重", "https://example.com/thread-1003-1-1.html", "", BTIH_B, "x"],
        ["综合讨论区", "无 tid 重复链接", "https://example.com/thread-1003-1-1.html", "", "", "x"],
        ["综合讨论区", "", "https://example.com/thread-1004-1-1.html", "1004", "", "x"],  # 缺标题
        ["综合讨论区", "缺原帖链接", "", "1005", "", "x"],  # 缺 original_url
        ["综合讨论区", "列数不符"],  # 列数不符
        ["", "", "", "", "", ""],  # 空行
    ]
    src.write_bytes(_csv_bytes(header, rows, bom=True))

    # 默认 allow_posts=False（自动监听）必须拒绝
    try:
        normalize_import_csv(src, dest, frozenset({"ltx"}))
    except CsvFormatError as exc:
        assert "色花综合帖子" in str(exc)
    else:
        raise AssertionError("posts csv should be rejected when allow_posts=False")

    # allow_posts=True（手动 /import）通过，且不会触发 ltx rehash
    result = normalize_import_csv(src, dest, frozenset({"ltx"}), allow_posts=True)
    assert result.kind == "posts"
    assert (result.total, result.written, result.duplicates, result.rehashed) == (8, 3, 2, 0)
    assert dict(result.bad) == {"title": 1, "original_url": 1, "columns": 1}
    assert result.unknown_columns == ["extra_col"]
    assert not dest.read_bytes().startswith(b"\xef\xbb\xbf")

    with dest.open(encoding="utf-8", newline="") as fh:
        reader = _csv.reader(fh)
        out_header = next(reader)
        out_rows = [dict(zip(out_header, row)) for row in reader]
    assert out_header == POST_CSV_COLUMNS
    assert [row["title"] for row in out_rows] == ["无磁力纯图帖", "多行 ed2k 帖", "无 tid 按链接去重"]
    assert out_rows[0]["magnet_link"] == ""
    assert out_rows[0]["is_downloaded"] == "false"
    assert out_rows[0]["images"] == "[]"
    assert out_rows[0]["attachments"] == "[]"
    assert out_rows[1]["magnet_link"] == f"{ED2K_C}\n{BTIH_A}"


def test_manual_import_routes_posts_csv_to_posts_endpoint_with_add_only(tmp_path: Path) -> None:
    content = _csv_bytes(
        ["id", "title", "tid", "original_url", "board_name", "magnet_link"],
        [
            ["1", "综合帖 A", "3931274", "https://example.com/thread-3931274-1-1.html", "综合讨论区", ""],
            ["2", "综合帖 A 重复", "3931274", "https://example.com/thread-3931274-1-2.html", "综合讨论区", ""],
            ["3", "综合帖 B", "3932163", "https://example.com/thread-3932163-1-1.html", "综合讨论区", ED2K_C],
        ],
    )
    magnet_importer = FakeImporter()
    posts_importer = FakeImporter(
        result={
            "success": True,
            "data": {"total_records": 2, "posts_imported": 1, "posts_updated": 0, "posts_skipped": 1, "errors": []},
        }
    )
    # 即使后台开启了 update_existing=True，帖子导入也必须强制 merge_strategy="add"
    module = make_module(tmp_path, importer=magnet_importer, posts_importer=posts_importer, update_existing=True)
    replied = make_message(name="posts_data_incremental_2026-11-23.csv", username="example_sender", message_id=96716, size=len(content))
    client = FakeClient(content)
    command = _command(replied)

    result = asyncio.run(_dispatch(module, command, client))

    assert result.status == "handled"
    assert magnet_importer.calls == []  # 绝不进入磁力主表 /api/data/import
    assert len(posts_importer.calls) == 1
    call = posts_importer.calls[0]
    assert call["merge_strategy"] == "add"
    assert call["validate_data"] is True
    with _io.StringIO(call["content"].decode("utf-8")) as buf:
        reader = _csv.reader(buf)
        assert next(reader) == POST_CSV_COLUMNS
        assert len(list(reader)) == 2
    final = command.edits[-1]
    assert final.startswith("✅ 已导入 色花综合帖子 posts_data_incremental_2026-11-23.csv")
    assert "文件内重复 1 行" in final
    assert "新增 1，跳过 1，更新 0，错误 0" in final
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []


def test_auto_import_rejects_posts_csv_even_when_filename_matches(tmp_path: Path) -> None:
    content = _csv_bytes(
        ["title", "tid", "original_url", "board_name", "magnet_link"],
        [["综合帖", "3931274", "https://example.com/thread-3931274-1-1.html", "综合讨论区", ""]],
    )
    magnet_importer = FakeImporter()
    posts_importer = FakeImporter()
    module = make_module(
        tmp_path,
        importer=magnet_importer,
        posts_importer=posts_importer,
        file_name_pattern=r"^posts_data.*\.csv$",
    )
    client = FakeClient(content)

    msg = make_message(name="posts_data_incremental_2026-11-23.csv", message_id=96716, size=len(content))
    asyncio.run(_dispatch(module, msg, client))

    assert magnet_importer.calls == []
    assert posts_importer.calls == []
    assert client.sent == []
    assert module.card.metrics["last"]["status"] == "failed"
    assert "色花综合帖子" in module.card.metrics["last"]["detail"]
    assert list((tmp_path / "runtime/tmp/magnet_import").iterdir()) == []


def test_import_posts_csv_sync_uses_query_params_and_posts_endpoint(tmp_path: Path, monkeypatch) -> None:
    import httpx

    recorded: list[dict[str, object]] = []

    class DummyResp:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    class DummyClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            recorded.append({"url": url, "params": kwargs.get("params"), "has_file": "file" in (kwargs.get("files") or {})})
            if url.endswith("/api/auth/login"):
                return DummyResp(200, {"success": True})
            return DummyResp(200, {"success": True, "data": {"posts_imported": 3, "posts_skipped": 1, "errors": []}})

    monkeypatch.setattr(httpx, "Client", DummyClient)
    csv_path = tmp_path / "posts.csv"
    csv_path.write_text(",".join(POST_CSV_COLUMNS) + "\n", encoding="utf-8")

    payload = import_posts_csv_sync("http://127.0.0.1:8022/", "admin", "pw", csv_path, "posts_data.csv")
    assert payload["data"]["posts_imported"] == 3
    assert recorded[1]["url"] == "http://127.0.0.1:8022/api/posts/import"
    assert recorded[1]["params"] == {"merge_strategy": "add", "validate_data": "true"}
    assert recorded[1]["has_file"] is True
