from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.config import AppConfig, RexWidgetSyncConfig, rex_widget_sync_config_from_dict
from telegram_bot.modules import create_default_registry
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.rex_widget_sync import RexWidgetSyncModule
from telegram_bot.shared.rex_widget_post import is_newer, parse_widget_post

CHAT = "-1000000000006"


class FakeHub:
    def __init__(self, modules: list[dict] | None = None, members: list[str] | None = None) -> None:
        self.modules = {m["id"]: dict(m) for m in (modules or [])}
        self.members = list(members or [])
        self.calls: list[tuple] = []
        self._n = 0

    def list_modules(self):
        return list(self.modules.values())

    def find_collection(self, slug):
        return {"id": "col1", "slug": slug, "moduleIds": list(self.members)}

    def upload_new(self, filename, content, *, group_id=""):
        self._n += 1
        mid = f"m{self._n}"
        self.modules[mid] = {"id": mid, "filename": filename, "content_hash": hashlib.sha256(content).hexdigest()}
        self.calls.append(("new", filename))
        return {"ok": True, "status": "added", "module_id": mid}

    def replace(self, module_id, filename, content, *, mode=""):
        self.modules[module_id].update(filename=filename, content_hash=hashlib.sha256(content).hexdigest())
        self.calls.append(("replace", module_id, filename, mode))
        return {"ok": True, "status": "replaced", "module_id": module_id}

    def update_meta(self, module_id, *, title="", version="", lock_title=True):
        self.modules[module_id].update(title=title, version=version)
        self.calls.append(("meta", module_id, title, version))

    def append_to_collection(self, collection_id, module_id):
        self.members.append(module_id)
        self.calls.append(("append", module_id))

    def delete_module(self, module_id):
        self.modules.pop(module_id, None)
        self.calls.append(("delete", module_id))

    def close(self):
        pass


def _msg(mid: int, name: str | None, caption: str = "", content: bytes = b"REXENC\nxx", chat: str = CHAT):
    async def download_media(file=None):
        return content

    file = SimpleNamespace(name=name, size=len(content)) if name else None
    return SimpleNamespace(id=mid, chat_id=chat, message=caption, file=file, download_media=download_media)


def _module(tmp_path: Path, hub: FakeHub, **overrides) -> RexWidgetSyncModule:
    overrides.setdefault("channel_chat", CHAT)
    overrides.setdefault("hub_base_url", "http://127.0.0.1:3398")
    overrides.setdefault("collection_slug", "example")
    config = RexWidgetSyncConfig(hub_password="pw", state_store=str(tmp_path / "state.json"), **overrides)
    card = ModuleCard(id="rex_widget_sync", name="Rex", description="", category="automation", enabled=True)
    return RexWidgetSyncModule(card, config, tmp_path, hub_factory=lambda _config: hub)


def _run(module: RexWidgetSyncModule, *messages) -> None:
    async def go():
        await module.start()
        for message in messages:
            await module.handle_message(SimpleNamespace(message=message))
        await module.wait_idle()

    asyncio.run(go())


def test_parse_widget_post_strips_versions_and_rex_tags() -> None:
    assert parse_widget_post("pornhub 2.2.7.js", "PornHub v2.2.7 模块\n#REX").key == "pornhub"
    post = parse_widget_post("anime1.2.2.0.js", "anime1 v2.2.0 模块")
    assert (post.key, post.version) == ("anime1", "2.2.0")
    assert parse_widget_post("Anime1-2.2.0.js").key == "anime1"
    aptv = parse_widget_post("APTV(rex).js", "APTV 直播源\n 作者 Speedo\n 版本 v1.10.6")
    assert (aptv.key, aptv.version, aptv.title) == ("aptv", "1.10.6", "APTV 直播源")
    # 文件名与文案版本不一致时取较高者
    assert parse_widget_post("JAVASS-v1.0.9.js", "JAVASS v1.0.6 模块").version == "1.0.9"
    assert parse_widget_post("春风里 1.7.2 .js", "春风里 1.7.2 模块").key == "春风里"
    assert parse_widget_post("2048.js", "2048 AI短剧 v1.0.16 模块").version == "1.0.16"
    assert is_newer("1.10.0", "1.9.9") and not is_newer("1.0", "1.0.0")


def test_new_module_is_uploaded_titled_and_added_to_collection(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(module, _msg(10, "pornhub 2.2.7.js", "PornHub v2.2.7 模块"))
    assert hub.calls == [("new", "pornhub 2.2.7.js"), ("meta", "m1", "PornHub", "2.2.7"), ("append", "m1")]
    assert module.card.metrics["added"] == 1
    assert module.card.metrics["last_message_id"] == 10


def test_higher_version_replaces_and_lower_or_same_is_skipped(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(
        module,
        _msg(10, "pornhub 2.2.7.js", "PornHub v2.2.7 模块", b"REXENC\nv1"),
        _msg(11, "pornhub 2.2.6.js", "PornHub v2.2.6 模块", b"REXENC\nold"),
        _msg(12, "pornhub 2.3.0.js", "PornHub v2.3.0 模块", b"REXENC\nv2"),
    )
    kinds = [c[0] for c in hub.calls]
    assert kinds.count("new") == 1
    assert ("replace", "m1", "pornhub 2.3.0.js", "") in hub.calls
    assert hub.modules["m1"]["version"] == "2.3.0"
    assert kinds.count("append") == 1  # 替换保留合集成员，不重复追加
    assert module.card.metrics["updated"] == 1


def test_without_version_content_hash_decides(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(module, _msg(1, "youtube.js", "", b"REXENC\na"), _msg(2, "youtube (rex).js", "", b"REXENC\na"), _msg(3, "youtube.js", "", b"REXENC\nb"))
    assert [c[0] for c in hub.calls].count("replace") == 1


def test_existing_hub_module_matched_by_filename_key_when_state_missing(tmp_path: Path) -> None:
    hub = FakeHub([{"id": "x", "filename": "anime1.2.1.0.js", "version": "2.1.0", "source_url": "https://a"}], ["x"])
    module = _module(tmp_path, hub)
    _run(module, _msg(5, "Anime1-2.2.0.js", "anime1 v2.2.0 模块"))
    assert ("replace", "x", "Anime1-2.2.0.js", "manual") in hub.calls
    assert not any(c[0] == "append" for c in hub.calls)


def test_ignores_other_chats_forward_variants_and_non_js(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(
        module,
        _msg(1, "a 1.0.js", chat="-100999"),
        _msg(2, "IPTV电视直播(FW).js"),
        _msg(3, "Youtube.rex"),
        _msg(4, None, "公告"),
    )
    assert hub.calls == []
    assert module.card.metrics["last_message_id"] == 4


def test_follows_module_link_when_post_has_no_attachment(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    linked = _msg(42730, "央视频直播.js", content=b"REXENC\ncode")
    fetched: list[tuple] = []

    async def get_messages(entity, ids):
        fetched.append((entity, ids))
        return linked if ids == 42730 else _msg(ids, "source.json")

    post = _msg(458, None, "央视频直播 v1.0.4 模块\n附上地址：https://t.me/c/0000000007/42696\n\n模块地址：https://t.me/c/0000000007/42730")
    post.client = SimpleNamespace(get_messages=get_messages)
    _run(module, post)
    assert fetched == [(-1000000000007, 42730)]
    assert ("meta", "m1", "央视频直播", "1.0.4") in hub.calls


def test_full_scan_keeps_only_latest_version_per_module(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    history = [
        _msg(1, "pornhub 2.2.6.js", "PornHub v2.2.6 模块"),
        _msg(2, "pornhub 2.2.7.js", "PornHub v2.2.7 模块"),
        _msg(3, "斗鱼直播 1.1.0.js", "douyu 直播 v1.1.0 模块"),
    ]

    async def reader(chat, *, min_id=0):
        for message in history:
            if message.id > min_id:
                yield message

    module.set_history_reader(reader)

    async def go():
        await module.start()
        assert module.request_scan(full=True)
        await module.wait_idle()

    asyncio.run(go())
    assert [c for c in hub.calls if c[0] == "new"] == [("new", "pornhub 2.2.7.js"), ("new", "斗鱼直播 1.1.0.js")]
    assert module.card.metrics["last_message_id"] == 3
    assert module.card.metrics["scanning"] is False


def test_hub_failure_marks_pending_and_missing_password_fails(tmp_path: Path) -> None:
    class BrokenHub(FakeHub):
        def upload_new(self, *args, **kwargs):
            raise RuntimeError("boom")

    module = _module(tmp_path, BrokenHub())
    _run(module, _msg(7, "a 1.0.js", "a v1.0"))
    assert module.card.metrics["pending_from"] == 7
    assert module.card.metrics["last"]["status"] == "failed"

    no_pw = _module(tmp_path / "b", FakeHub())
    no_pw.config.hub_password = ""
    _run(no_pw, _msg(8, "a 1.0.js"))
    assert "密码" in no_pw.card.metrics["last"]["detail"]


def test_config_parsing_and_password_masking(tmp_path: Path) -> None:
    config = rex_widget_sync_config_from_dict({"hub_password": "s", "max_file_size_mb": 999, "file_name_pattern": "("})
    assert config.max_file_size_mb == 25
    assert config.file_name_pattern == RexWidgetSyncConfig().file_name_pattern
    module = _module(tmp_path, FakeHub())
    assert module.card.config["hub_password"] == "" and module.card.config["has_hub_password"] is True
    module.update_config({"hub_password": "", "collection_slug": "other"})
    assert module.config.hub_password == "pw" and module.config.collection_slug == "other"
    ids = {card["id"] for card in create_default_registry(AppConfig()).cards()}
    assert "rex_widget_sync" in ids
    assert AppConfig.from_dict(AppConfig.defaults_dict()).rex_widget_sync.channel_chat == ""


def test_forward_encrypted_files_are_skipped_not_failed(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(module, _msg(74, "huya.js", "huya直播", b"FWENC2\n{}\nxx"))
    assert hub.calls == []
    assert module.card.metrics["last"]["status"] == "skipped"
    assert module.card.metrics["pending_from"] == 0


def test_parse_strips_platform_suffixes_without_eating_name_letters() -> None:
    assert parse_widget_post("AVDB 2.1.3-REX.js").key == "avdb"
    assert parse_widget_post("AVDB 2.1.1 Rex版.js").key == "avdb"
    assert parse_widget_post("AVDB 2.1.0.js").key == "avdb"
    post = parse_widget_post("Stripchat-v6.1.3-rexenc.js")
    assert (post.key, post.version) == ("stripchat", "6.1.3")
    assert parse_widget_post("PubJAV 1.2.2.js", "Pubjav v1.2.2 模块").key == "pubjav"
    assert parse_widget_post("MissAV 3.2.1.js", "MissAV v3.2.1").key == "missav"
    assert parse_widget_post("xiaodengta.enc.js").key == "xiaodengta"
    assert parse_widget_post("Forex.js").key == "forex"
    assert parse_widget_post("x.js", "JAVday 更新日志\nv1.5.1").title == "JAVday"


def test_plain_scripts_without_widget_metadata_are_skipped_and_plain_modules_keep_code_title(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    _run(
        module,
        _msg(1, "worker-v38.js", "worker", b"export default { fetch() {} }"),
        _msg(2, "jable.js", "Jable 更新日志 v2.5.0", b"var WidgetMetadata = { id: 'jable' }"),
    )
    assert hub.calls == [("new", "jable.js"), ("append", "m1")]


def test_ignored_keys_are_never_synced(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub, ignore_keys=["douyu"])
    _run(module, _msg(1, "douyu.js", "douyu v1.2"), _msg(2, "斗鱼直播 1.1.0.js", "douyu 直播 v1.1.0 模块"))
    assert [c for c in hub.calls if c[0] == "new"] == [("new", "斗鱼直播 1.1.0.js")]
    assert rex_widget_sync_config_from_dict({"ignore_keys": [" Douyu ", ""]}).ignore_keys == ["douyu"]


def test_full_scan_prefers_later_post_without_version_and_reads_code_version(tmp_path: Path) -> None:
    hub = FakeHub()
    module = _module(tmp_path, hub)
    code = b'var WidgetMetadata = { id: "pan115_rex", title: "Pan115", version: "1.15.0" };'
    history = [
        _msg(21, "pan115_v1.3.1-stable.js", "115 网盘模块\n版本: 1.3.1", b"var WidgetMetadata = {version: '1.3.1'}"),
        _msg(204, "Pan115.js", "Pan115 更新日志", code),
    ]

    async def reader(chat, *, min_id=0):
        for message in history:
            yield message

    module.set_history_reader(reader)

    async def go():
        await module.start()
        module.request_scan(full=True)
        await module.wait_idle()

    asyncio.run(go())
    assert [c for c in hub.calls if c[0] == "new"] == [("new", "Pan115.js")]
    assert not any(c[0] == "meta" for c in hub.calls)  # 未加密模块版本由 Hub 从代码读取
    assert module._entries()["pan115"]["version"] == "1.15.0"
    assert parse_widget_post("儿歌点点v1.0.1.js", "儿歌点点 v1.0.1").key == "儿歌点点"


def test_plain_module_keeps_code_version_and_recreates_when_code_id_changes(tmp_path: Path) -> None:
    hub = FakeHub([{"id": "x", "filename": "pan115_v1.3.1-stable.js", "version": "1.3.1",
                    "widget_id": "pan115_v1", "metadata_id": "pan115_v1"}], ["x"])
    original_replace = hub.replace

    def replace(module_id, filename, content, *, mode=""):
        result = original_replace(module_id, filename, content, mode=mode)
        hub.modules[module_id]["metadata_id"] = "pan115_rex"  # Hub 按新代码更新 metadata_id，widget_id 不变
        return result

    hub.replace = replace
    module = _module(tmp_path, hub)
    code = b'WidgetMetadata = { id: "pan115_rex", version: "1.15.0", requiredVersion: "0.0.1" }'
    _run(module, _msg(204, "Pan115.js", "Pan115 \u66f4\u65b0\u65e5\u5fd7 v9.9", code))
    kinds = [c[0] for c in hub.calls]
    assert kinds == ["replace", "delete", "new", "append"]
    assert module._entries()["pan115"]["version"] == "1.15.0"  # 用代码版本，不用文案 v9.9


def test_encrypted_module_switching_to_plain_code_is_recreated(tmp_path: Path) -> None:
    # 旧版 REXENC：Hub 读不到元信息，widget_id 就是 Hub uuid；新版明文带代码 id
    hub = FakeHub([{"id": "u1", "filename": "全豆要音源-2.7.3.js", "version": "2.7.3",
                    "widget_id": "u1", "metadata_id": ""}], ["u1"])
    original_replace = hub.replace

    def replace(module_id, filename, content, *, mode=""):
        result = original_replace(module_id, filename, content, mode=mode)
        hub.modules[module_id]["metadata_id"] = "forward.quandouya.full"
        return result

    hub.replace = replace
    module = _module(tmp_path, hub)
    code = b'WidgetMetadata = { id: "forward.quandouya.full", version: "2.7.7" }'
    _run(module, _msg(467, "全豆要音源-2.7.7.js", "全豆要音源 v2.7.7", code))
    assert [c[0] for c in hub.calls] == ["replace", "delete", "new", "append"]
    assert module._entries()["全豆要音源"]["hub_id"] == "m1"
