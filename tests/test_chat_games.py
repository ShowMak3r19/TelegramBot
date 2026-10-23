from __future__ import annotations

import asyncio
from pathlib import Path

from telegram_bot.config import (
    ChatGamesConfig,
    EmojiRiddleConfig,
    EmojiRiddleItemConfig,
    GarbledDecodeConfig,
    LuckyWordConfig,
)
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.chat_games import ChatGamesModule, _normalize_answer, render_emoji_riddle_png, render_garbled_decode_png


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool = False,
        chat_id: int = -100123,
        sender_id: int = 10,
        message_id: int = 1,
    ) -> None:
        self.raw_text = text
        self.out = out
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.id = message_id
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeSentMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class FakeClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.sent_files: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.next_id = 1000

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> FakeSentMessage:
        self.next_id += 1
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return FakeSentMessage(self.next_id)

    async def send_file(self, chat_id: int, file: str, **kwargs: object) -> FakeSentMessage:
        self.next_id += 1
        self.sent_files.append({"chat_id": chat_id, "file": file, **kwargs})
        return FakeSentMessage(self.next_id)

    async def edit_message(self, chat_id: int, message_id: int, text: str, **kwargs: object) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, **kwargs})


class FakeEvent:
    def __init__(self, message: FakeMessage, client: FakeClient | None = None) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.sender_id = message.sender_id
        self.client = client or FakeClient()


def make_module(tmp_path: Path, config: ChatGamesConfig | None = None) -> ChatGamesModule:
    config = config or ChatGamesConfig()
    config.state_store = str(tmp_path / "chat_games_state.json")
    config.output_dir = str(tmp_path / "generated_chat_games")
    return ChatGamesModule(ModuleCard("chat_games", "聊天小游戏", "", "game", enabled=True), config, tmp_path)


def test_lucky_word_awards_matching_message_once_per_chat(tmp_path: Path) -> None:
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(words=["咖啡"], daily_limit_per_chat=1, per_user_daily_limit=1),
        emoji_riddle=EmojiRiddleConfig(enabled=False),
        garbled_decode=GarbledDecodeConfig(enabled=False),
    )
    module = make_module(tmp_path, config)
    client = FakeClient()

    first = FakeEvent(FakeMessage("咖啡续命", sender_id=1, message_id=11), client)
    second = FakeEvent(FakeMessage("再来一杯咖啡", sender_id=2, message_id=12), client)

    assert asyncio.run(module.handle_message(first)).status == "handled"
    assert client.sent_messages[-1]["text"] == "+100"
    assert client.sent_messages[-1]["reply_to"] == 11
    assert asyncio.run(module.handle_message(second)).status == "ignored"
    assert len(client.sent_messages) == 1


def test_lucky_word_ignores_commands_and_reward_messages(tmp_path: Path) -> None:
    config = ChatGamesConfig(lucky_word=LuckyWordConfig(words=["咖啡"], daily_limit_per_chat=5))
    module = make_module(tmp_path, config)
    client = FakeClient()

    command = FakeEvent(FakeMessage("/咖啡", sender_id=1, message_id=21), client)
    reward = FakeEvent(FakeMessage("+100 咖啡", sender_id=1, message_id=22), client)

    assert asyncio.run(module.handle_message(command)).status == "ignored"
    assert asyncio.run(module.handle_message(reward)).status == "ignored"
    assert client.sent_messages == []


def test_emoji_riddle_first_correct_answer_awards_immediately(tmp_path: Path) -> None:
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(enabled=False),
        emoji_riddle=EmojiRiddleConfig(
            duration_seconds=60,
            announce_answer=False,
            items=[EmojiRiddleItemConfig("🌧️ + 🏠 + 🐟", ["漏网之鱼"])],
        ),
        garbled_decode=GarbledDecodeConfig(enabled=False),
    )
    module = make_module(tmp_path, config)
    client = FakeClient()

    async def run_case() -> None:
        await module.handle_message(FakeEvent(FakeMessage("/emoji 250", out=True, sender_id=99, message_id=31), client))
        assert len(client.sent_files) == 1
        answer = FakeEvent(FakeMessage("漏 网 之 鱼", sender_id=2, message_id=32), client)
        result = await module.handle_message(answer)
        assert result.status == "handled"

    asyncio.run(run_case())
    assert client.sent_messages[-1]["text"] == "+250"
    assert client.sent_messages[-1]["reply_to"] == 32
    assert client.edits == []
    assert module.active_games == {}


def test_emoji_riddle_marks_prompt_with_answer_without_extra_message(tmp_path: Path) -> None:
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(enabled=False),
        emoji_riddle=EmojiRiddleConfig(
            duration_seconds=60,
            announce_answer=True,
            items=[EmojiRiddleItemConfig("🌧️ + 🏠 + 🐟", ["漏网之鱼"])],
        ),
        garbled_decode=GarbledDecodeConfig(enabled=False),
    )
    module = make_module(tmp_path, config)
    client = FakeClient()

    async def run_case() -> None:
        await module.handle_message(FakeEvent(FakeMessage("/emoji 250", out=True, sender_id=99, message_id=31), client))
        answer = FakeEvent(FakeMessage("漏网之鱼", sender_id=2, message_id=32), client)
        result = await module.handle_message(answer)
        assert result.status == "handled"

    asyncio.run(run_case())
    assert len(client.sent_messages) == 1
    assert client.sent_messages[0]["text"] == "+250"
    assert client.edits[-1]["message_id"] == 1001
    assert "已答中" in str(client.edits[-1]["text"])
    assert "答案：漏网之鱼" in str(client.edits[-1]["text"])


def test_garbled_decode_timeout_announces_answer(tmp_path: Path) -> None:
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(enabled=False),
        emoji_riddle=EmojiRiddleConfig(enabled=False),
        garbled_decode=GarbledDecodeConfig(
            duration_seconds=0.05,
            announce_answer=True,
            phrases=["服务器又活了"],
        ),
    )
    module = make_module(tmp_path, config)
    client = FakeClient()

    async def run_case() -> None:
        await module.handle_message(FakeEvent(FakeMessage("/decode", out=True, sender_id=99, message_id=41), client))
        assert len(client.sent_files) == 1
        await asyncio.sleep(0.2)

    asyncio.run(run_case())
    assert client.sent_messages == []
    assert client.edits[-1]["message_id"] == 1001
    assert "本轮无人答中" in str(client.edits[-1]["text"])
    assert "答案：服务器又活了" in str(client.edits[-1]["text"])


def test_garbled_decode_accepts_inline_custom_phrase(tmp_path: Path) -> None:
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(enabled=False),
        emoji_riddle=EmojiRiddleConfig(enabled=False),
        garbled_decode=GarbledDecodeConfig(duration_seconds=60, announce_answer=False, phrases=[]),
    )
    module = make_module(tmp_path, config)
    client = FakeClient()

    async def run_case() -> None:
        await module.handle_message(FakeEvent(FakeMessage("/decode 300 今晚重启NAS", out=True, sender_id=99, message_id=51), client))
        assert len(client.sent_files) == 1
        answer = FakeEvent(FakeMessage("今晚重启NAS", sender_id=2, message_id=52), client)
        result = await module.handle_message(answer)
        assert result.status == "handled"

    asyncio.run(run_case())
    assert client.sent_messages[-1]["text"] == "+300"
    assert client.sent_messages[-1]["reply_to"] == 52
    assert client.edits == []


def test_emoji_riddle_renderer_uses_readable_fallback_tokens(tmp_path: Path) -> None:
    output = tmp_path / "emoji.png"
    render_emoji_riddle_png(EmojiRiddleItemConfig("🌧️ + 🏠 + 🐟", ["漏网之鱼"]), output)
    assert output.exists()
    assert output.stat().st_size > 0


def test_garbled_decode_normalizes_emoji_answers_to_text() -> None:
    assert _normalize_answer("\U0001f336\ufe0f\U0001f414bot") == _normalize_answer("\u8fa3\u9e21bot")
    assert _normalize_answer("\U0001f336\ufe0f\U0001f414bot") != _normalize_answer("bot")


def test_garbled_decode_renderer_creates_png(tmp_path: Path) -> None:
    output = tmp_path / "decode.png"
    render_garbled_decode_png("今天加鸡腿", output)
    assert output.exists()
    assert output.stat().st_size > 0
