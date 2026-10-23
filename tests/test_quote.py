from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import telegram_bot.shared.quote_api as quote_api
from telegram_bot.config import QuoteConfig
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.quote import QuoteModule, _build_quote_user, _hash_id, parse_quote_command


def _make_entity(cls_name: str, offset: int, length: int, **extra):
    cls = type(cls_name, (), {})
    entity = cls()
    entity.offset = offset
    entity.length = length
    for key, value in extra.items():
        setattr(entity, key, value)
    return entity


# ---- 命令解析 ----


def test_parse_quote_command_basic() -> None:
    prefixes = ["/q", "语录"]
    assert parse_quote_command("/q", prefixes) == {"kind": "generate", "count": 1, "with_reply": False}
    assert parse_quote_command("语录", prefixes) == {"kind": "generate", "count": 1, "with_reply": False}
    assert parse_quote_command("/q 3", prefixes) == {"kind": "generate", "count": 3, "with_reply": False}
    assert parse_quote_command("语录 2", prefixes) == {"kind": "generate", "count": 2, "with_reply": False}


def test_parse_quote_command_subcommands() -> None:
    prefixes = ["/q", "语录"]
    assert parse_quote_command("/q r 2", prefixes) == {"kind": "generate", "count": 2, "with_reply": True}
    assert parse_quote_command("/q r", prefixes) == {"kind": "generate", "count": 1, "with_reply": True}
    assert parse_quote_command("/q s", prefixes) == {"kind": "save"}
    assert parse_quote_command("/q f 你好世界", prefixes) == {"kind": "fake", "content": "你好世界"}
    assert parse_quote_command("/q config sticker mypack", prefixes) == {"kind": "config", "args": ["sticker", "mypack"]}


def test_parse_quote_command_non_match() -> None:
    prefixes = ["/q", "语录"]
    assert parse_quote_command("hello", prefixes) is None
    assert parse_quote_command("", prefixes) is None
    assert parse_quote_command("语录r", prefixes) is None  # 中文前缀要求空格分隔，避免误触发


# ---- 实体转换 ----


def test_convert_entities() -> None:
    entities = [
        _make_entity("MessageEntityBold", 0, 4),
        _make_entity("MessageEntityTextUrl", 5, 3, url="http://x.com"),
        _make_entity("MessageEntityCustomEmoji", 9, 2, document_id=12345),
        _make_entity("UnknownEntity", 11, 1),
    ]
    result = quote_api.convert_entities(entities)
    assert result[0] == {"offset": 0, "length": 4, "type": "bold"}
    assert result[1] == {"offset": 5, "length": 3, "type": "text_link", "url": "http://x.com"}
    assert result[2] == {"offset": 9, "length": 2, "type": "custom_emoji", "custom_emoji_id": "12345"}
    assert result[3] == {"offset": 11, "length": 1}  # 未知类型只保留 offset/length


# ---- 格式检测 ----


def test_format_detection() -> None:
    assert quote_api.is_webm(b"\x1a\x45\xdf\xa3xxxx")
    assert quote_api.is_gzip_tgs(b"\x1f\x8bxxxx")
    assert quote_api.is_mp4(b"\x00\x00\x00\x18ftypisom")
    assert not quote_api.is_webm(b"RIFFxxxx")
    assert quote_api.webp_dimensions(b"\x1a\x45\xdf\xa3" + b"\x00" * 20) == (512, 512)
    assert quote_api.webp_dimensions(b"tooshort") == (512, 768)


def test_build_quote_payload() -> None:
    payload = quote_api.build_quote_payload([{"text": "hi"}], QuoteConfig())
    assert payload["type"] == "quote"
    assert payload["backgroundColor"] == "#1b1429"
    assert payload["width"] == 512
    assert payload["messages"] == [{"text": "hi"}]


def test_hash_id_is_stable_int() -> None:
    assert _hash_id("abc") == _hash_id("abc")
    assert isinstance(_hash_id("x"), int)
    assert _hash_id("a") != _hash_id("b")


# ---- handle 流程（mock telethon 发送 + quote-api）----


class FakeSender:
    def __init__(self, sid: int, first_name: str = "", last_name: str = "", username: str = "") -> None:
        self.id = sid
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.name = f"{first_name} {last_name}".strip()


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool = False,
        is_reply: bool = False,
        reply: "FakeMessage | None" = None,
        sender: FakeSender | None = None,
        message_id: int = 1,
        reply_to: object | None = None,
    ) -> None:
        self.raw_text = text
        self.message = text
        self.out = out
        self.is_reply = is_reply
        self._reply = reply
        self._sender = sender
        self.id = message_id
        self.reply_to = reply_to
        self.chat_id = -100
        self.entities: list = []
        self.media = None
        self.fwd_from = None
        self.edits: list[str] = []
        self.deleted = False

    async def get_sender(self):
        return self._sender

    async def get_reply_message(self):
        return self._reply

    async def edit(self, text: str, **kwargs):
        self.edits.append(text)

    async def delete(self):
        self.deleted = True

    async def download_media(self, file=None, **kwargs):
        return b""


class FakeClient:
    async def download_profile_photo(self, sender, file=None, **kwargs):
        return b"avatarbytes"

    async def get_messages(self, chat_id, **kwargs):
        return []


class FakeEvent:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.client = FakeClient()


class StubQuoteModule(QuoteModule):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sent: list[bytes] = []

    async def _send_quote_sticker(self, event, replied, buffer) -> None:
        self.sent.append(buffer)


def _module(tmp_path: Path) -> StubQuoteModule:
    return StubQuoteModule(ModuleCard("quote", "语录", "", "media", enabled=True), QuoteConfig(), tmp_path)


def test_quote_generate_sends_sticker(tmp_path: Path) -> None:
    original = quote_api.generate_quote_sync
    quote_api.generate_quote_sync = lambda url, payload, timeout: b"RIFF\x00\x00\x00\x00WEBPfake"
    try:
        module = _module(tmp_path)
        replied = FakeMessage("被引用内容", sender=FakeSender(123, "Tester"), message_id=50)
        trigger = FakeMessage("/q", out=True, is_reply=True, reply=replied, message_id=51)
        result = asyncio.run(module.handle_message(FakeEvent(trigger)))
        assert result.status == "handled"
        assert len(module.sent) == 1
        assert trigger.deleted is True
    finally:
        quote_api.generate_quote_sync = original


def test_quote_generate_uses_selected_reply_quote_text(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    original = quote_api.generate_quote_sync

    def fake_generate(url, payload, timeout):
        captured["payload"] = payload
        return b"RIFF\x00\x00\x00\x00WEBPfake"

    quote_api.generate_quote_sync = fake_generate
    try:
        module = _module(tmp_path)
        replied = FakeMessage("开头 只想引用这一段 结尾", sender=FakeSender(123, "Tester"), message_id=50)
        replied.entities = [_make_entity("MessageEntityBold", 0, 2)]
        quote_entity = _make_entity("MessageEntityItalic", 0, 8)
        trigger = FakeMessage(
            "/q",
            out=True,
            is_reply=True,
            reply=replied,
            message_id=51,
            reply_to=SimpleNamespace(
                reply_to_msg_id=50,
                quote_text="只想引用这一段",
                quote_entities=[quote_entity],
            ),
        )

        result = asyncio.run(module.handle_message(FakeEvent(trigger)))
        message = captured["payload"]["messages"][0]  # type: ignore[index]

        assert result.status == "handled"
        assert message["text"] == "只想引用这一段"
        assert message["entities"] == [{"offset": 0, "length": 8, "type": "italic"}]
        assert "开头" not in message["text"]
        assert trigger.deleted is True
    finally:
        quote_api.generate_quote_sync = original


def test_quote_ignores_non_outgoing(tmp_path: Path) -> None:
    module = _module(tmp_path)
    trigger = FakeMessage("/q", out=False, is_reply=True, reply=FakeMessage("x", sender=FakeSender(1)))
    result = asyncio.run(module.handle_message(FakeEvent(trigger)))
    assert result.status == "ignored"
    assert not module.sent


def test_quote_requires_reply(tmp_path: Path) -> None:
    module = _module(tmp_path)
    trigger = FakeMessage("/q", out=True, is_reply=False)
    result = asyncio.run(module.handle_message(FakeEvent(trigger)))
    assert result.status == "handled"
    assert "请回复" in trigger.edits[-1]
    assert not module.sent


# ---- 发送者名字补全（修复名字里 emoji 丢失）----


class _BareSender:
    """模拟 Telethon User：无 .name 属性，名字由 first/last 组合。"""

    def __init__(self, sid: int, first_name: str, last_name: str = "") -> None:
        self.id = sid
        self.first_name = first_name
        self.last_name = last_name
        self.username = ""


def test_build_quote_user_enriches_missing_last_name() -> None:
    # get_sender 拿到的实体缺 last_name（只有“无著”），get_entity 返回完整带 emoji 的实体
    incomplete = _BareSender(123, "无著", "")

    class EnrichClient:
        async def get_entity(self, sid):
            assert sid == 123
            return _BareSender(123, "无著", "😄")

        async def download_profile_photo(self, sender, file=None, **kwargs):
            return b""

    user = asyncio.run(_build_quote_user(incomplete, EnrichClient(), True))
    assert user["name"] == "无著 😄"
    assert user["last_name"] == "😄"


def test_build_quote_user_falls_back_when_enrich_fails() -> None:
    sender = _BareSender(123, "无著", "😄")

    class FailingClient:
        async def get_entity(self, sid):
            raise RuntimeError("无法获取")

        async def download_profile_photo(self, sender, file=None, **kwargs):
            return b""

    # get_entity 失败时沿用原实体，仍保留原本就有的 last_name
    user = asyncio.run(_build_quote_user(sender, FailingClient(), True))
    assert user["name"] == "无著 😄"
