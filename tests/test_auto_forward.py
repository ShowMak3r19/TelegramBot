from __future__ import annotations

import asyncio
from types import SimpleNamespace

from telegram_bot.config import AutoForwardConfig
from telegram_bot.modules.auto_forward import AutoForwardModule, match_auto_forward_mode
from telegram_bot.modules.base import ModuleCard


class FakeClient:
    def __init__(self) -> None:
        self.forwarded: list[dict[str, object]] = []
        self.sent: list[dict[str, object]] = []

    async def forward_messages(self, chat_id: int, message: object) -> None:
        self.forwarded.append({"chat_id": chat_id, "message": message})

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool = True,
        is_reply: bool = False,
        reply: "FakeMessage | None" = None,
        message_id: int = 1,
        chat_id: int = -1001,
        sender: object | None = None,
        chat: object | None = None,
    ) -> None:
        self.raw_text = text
        self.out = out
        self.is_reply = is_reply
        self._reply = reply
        self.id = message_id
        self.chat_id = chat_id
        self.sender = sender
        self.chat = chat
        self.deleted = False
        self.edits: list[str] = []

    async def get_reply_message(self) -> "FakeMessage | None":
        return self._reply

    async def get_sender(self) -> object | None:
        return self.sender

    async def get_chat(self) -> object | None:
        return self.chat

    async def delete(self) -> None:
        self.deleted = True

    async def edit(self, text: str, **kwargs: object) -> None:
        self.edits.append(text)


class FakeEvent:
    def __init__(self, message: FakeMessage, client: FakeClient) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.client = client


def make_module() -> AutoForwardModule:
    return AutoForwardModule(ModuleCard("auto_forward", "auto forward", "", "automation", enabled=True), AutoForwardConfig())


def test_match_auto_forward_modes() -> None:
    config = AutoForwardConfig()

    assert match_auto_forward_mode(",re", config) == "native"
    assert match_auto_forward_mode(",copy", config) == "copy_text"
    assert match_auto_forward_mode(",quote", config) == "quote"
    assert match_auto_forward_mode(",link", config) == "link"
    assert match_auto_forward_mode(",unknown", config) is None


def test_native_forward_deletes_command() -> None:
    client = FakeClient()
    replied = FakeMessage("hello", out=False, message_id=9)
    command = FakeMessage(",re", is_reply=True, reply=replied, message_id=10)

    result = asyncio.run(make_module().handle_message(FakeEvent(command, client)))

    assert result.status == "handled"
    assert result.metadata["mode"] == "native"
    assert client.forwarded == [{"chat_id": -1001, "message": replied}]
    assert command.deleted is True


def test_copy_text_sends_plain_text_without_forward_author() -> None:
    client = FakeClient()
    replied = FakeMessage("plain text", out=False, message_id=9)
    command = FakeMessage(",copy", is_reply=True, reply=replied, message_id=10)

    result = asyncio.run(make_module().handle_message(FakeEvent(command, client)))

    assert result.status == "handled"
    assert client.forwarded == []
    assert client.sent == [{"chat_id": -1001, "text": "plain text", "kwargs": {}}]


def test_quote_mode_wraps_sender_and_text() -> None:
    client = FakeClient()
    sender = SimpleNamespace(id=123, first_name="Test", last_name="User", username="tester")
    replied = FakeMessage("quoted", out=False, message_id=9, sender=sender)
    command = FakeMessage(",quote", is_reply=True, reply=replied, message_id=10)

    result = asyncio.run(make_module().handle_message(FakeEvent(command, client)))

    assert result.status == "handled"
    assert "来自 Test User (@tester)" in str(client.sent[0]["text"])
    assert "<blockquote expandable>quoted</blockquote>" in str(client.sent[0]["text"])
    assert client.sent[0]["kwargs"] == {"parse_mode": "html"}


def test_link_mode_uses_public_chat_link() -> None:
    client = FakeClient()
    chat = SimpleNamespace(username="public_group")
    replied = FakeMessage("linked", out=False, message_id=99, chat=chat)
    command = FakeMessage(",link", is_reply=True, reply=replied, message_id=10)

    result = asyncio.run(make_module().handle_message(FakeEvent(command, client)))

    assert result.status == "handled"
    assert client.sent == [{"chat_id": -1001, "text": "https://t.me/public_group/99", "kwargs": {}}]


def test_link_mode_without_public_username_edits_command() -> None:
    client = FakeClient()
    replied = FakeMessage("linked", out=False, message_id=99)
    command = FakeMessage(",link", is_reply=True, reply=replied, message_id=10)

    result = asyncio.run(make_module().handle_message(FakeEvent(command, client)))

    assert result.status == "handled"
    assert result.metadata["mode"] == "link"
    assert client.sent
    assert "没有公开可点击链接" in str(client.sent[0]["text"])
    assert command.deleted is True


if __name__ == "__main__":
    test_match_auto_forward_modes()
    test_native_forward_deletes_command()
    test_copy_text_sends_plain_text_without_forward_author()
    test_quote_mode_wraps_sender_and_text()
    test_link_mode_uses_public_chat_link()
    test_link_mode_without_public_username_edits_command()
    print("PASS test_auto_forward")
