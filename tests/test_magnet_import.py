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
CONTENT = b"id,title\n" + b"x" * 3000


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
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error

    def __call__(self, base_url, username, password, file_path, file_name, **kwargs):
        self.calls.append(
            {"base_url": base_url, "username": username, "password": password, "name": file_name,
             "content": Path(file_path).read_bytes(), **kwargs}
        )
        if self.error:
            raise self.error
        return {"success": True, "data": {"imported": 10, "skipped": 2}}


def make_message(*, name="x1080x_all_2026-10-09.csv", username="example_sender", chat_id=CHAT_ID, message_id=7, size=None):
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender_id=123,
        sender=SimpleNamespace(username=username),
        document=SimpleNamespace(size=size if size is not None else len(CONTENT)),
        file=SimpleNamespace(name=name, size=size if size is not None else len(CONTENT)),
    )


def make_module(tmp_path: Path, importer=None, **overrides) -> MagnetImportModule:
    overrides.setdefault("watch_chats", [str(CHAT_ID)])
    overrides.setdefault("sender_usernames", ["example_sender"])
    config = MagnetImportConfig(api_password="secret", **overrides)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    module = MagnetImportModule(
        ModuleCard("magnet_import", "magnet", "", "automation", enabled=True),
        config,
        tmp_path,
        importer=importer or FakeImporter(),
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
    assert call["content"] == CONTENT
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
