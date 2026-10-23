from __future__ import annotations

import asyncio
from pathlib import Path

from telegram_bot.config import WordCloudConfig
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.word_cloud import (
    WordCloudModule,
    build_word_cloud_from_messages,
    collect_words,
    extract_word_cloud_prompt,
    parse_word_cloud_limit,
    render_word_cloud_png,
)


class FakeMessage:
    def __init__(self, text: str, *, out: bool = False, chat_id: int = -1001, message_id: int = 1) -> None:
        self.raw_text = text
        self.out = out
        self.chat_id = chat_id
        self.id = message_id
        self.deleted = False
        self.edits: list[str] = []

    async def delete(self) -> None:
        self.deleted = True

    async def edit(self, text: str, **kwargs: object) -> None:
        self.edits.append(text)


class FakeEvent:
    def __init__(self, message: FakeMessage, history: list[FakeMessage]) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.client = self
        self.history = history
        self.sent_messages: list[dict[str, object]] = []
        self.sent_files: list[dict[str, object]] = []

    async def iter_messages(self, chat_id: int, limit: int):
        for item in self.history[:limit]:
            yield item

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> FakeMessage:
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return FakeMessage(text, out=True, chat_id=chat_id, message_id=999)

    async def send_file(self, chat_id: int, **kwargs: object) -> None:
        self.sent_files.append({"chat_id": chat_id, **kwargs})


def test_word_cloud_prompt_and_limit() -> None:
    config = WordCloudConfig(default_limit=1000, min_limit=50, max_limit=2000)

    assert extract_word_cloud_prompt("cy", config) == ""
    assert extract_word_cloud_prompt("cy 500", config) == "500"
    assert extract_word_cloud_prompt("/cy 9999", config) == "9999"
    assert extract_word_cloud_prompt("cycle 500", config) is None
    assert parse_word_cloud_limit("", config) == 1000
    assert parse_word_cloud_limit("9999", config) == 2000
    assert parse_word_cloud_limit("1", config) == 50


def test_word_cloud_counts_are_per_supplied_chat_history() -> None:
    config = WordCloudConfig()
    chat_a = [FakeMessage("claude tokens tokens 中文 中文 配置"), FakeMessage("cy 500"), FakeMessage("/ai ignored")]
    chat_b = [FakeMessage("docker nas nas docker"), FakeMessage("docker nas")]

    words_a, valid_a = build_word_cloud_from_messages(chat_a, config)
    words_b, valid_b = build_word_cloud_from_messages(chat_b, config)

    assert valid_a == 1
    assert valid_b == 2
    assert {item["word"] for item in words_a} != {item["word"] for item in words_b}
    assert any(item["word"] == "tokens" for item in words_a)
    assert any(item["word"] == "docker" for item in words_b)


def test_render_word_cloud_png(tmp_path: Path) -> None:
    config = WordCloudConfig(width=640, height=420)
    counts = {}
    from collections import Counter

    counter: Counter[str] = Counter()
    collect_words("claude claude tokens tokens 中文 中文 docker docker nas nas", counter, config)
    words = [{"word": key, "count": value, "size": 40, "color": "#0f766e"} for key, value in counter.items()]
    output = tmp_path / "cloud.png"

    render_word_cloud_png(words, 100, 10, config, output)

    assert output.exists()
    assert output.stat().st_size > 1000


def test_word_cloud_command_uses_current_chat_and_sends_png(tmp_path: Path) -> None:
    config = WordCloudConfig(default_limit=50, output_dir=str(tmp_path), width=640, height=420)
    module = WordCloudModule(ModuleCard("word_cloud", "词云", "", "media", enabled=True), config, tmp_path)
    trigger = FakeMessage("cy 50", out=True, chat_id=-100123, message_id=7)
    history = [
        FakeMessage("claude claude tokens tokens 中文 中文 docker docker nas nas", chat_id=-100123),
        FakeMessage("配置 配置 模型 模型 查看 查看", chat_id=-100123),
    ]
    event = FakeEvent(trigger, history)

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert trigger.deleted is True
    assert event.sent_messages[0]["chat_id"] == -100123
    assert event.sent_files
    assert event.sent_files[0]["chat_id"] == -100123
    assert Path(str(event.sent_files[0]["file"])).exists()
