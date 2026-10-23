from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

from telegram_bot.config import AIConfig, AIProviderConfig, AIReplyConfig
from telegram_bot.modules import ai_reply as ai_reply_module
from telegram_bot.modules.ai_reply import (
    AIReplyModule,
    collect_image_inputs_for_responses,
    collect_short_context,
    extract_ai_prompt,
    extract_requested_image_indexes,
    format_ai_group_message,
    media_file_suffix,
    media_is_motion,
    media_is_tgs_sticker,
    media_may_be_video,
    representative_frame_positions,
)
from telegram_bot.modules.base import ModuleCard

TINY_GIF_BYTES = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")


class DocumentAttributeSticker:
    pass


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool = True,
        is_reply: bool = False,
        reply: "FakeMessage | None" = None,
        media: bool = False,
        media_bytes: bytes = b"",
        grouped_id: int | None = None,
        message_id: int = 10,
        sender: object | None = None,
        chat: object | None = None,
        action_log: list[str] | None = None,
    ) -> None:
        self.raw_text = text
        self.out = out
        self.is_reply = is_reply
        self._reply = reply
        self.media = object() if media else None
        self._media_bytes = media_bytes
        self.grouped_id = grouped_id
        self.edits: list[str] = []
        self.deleted = False
        self.chat_id = 1
        self.id = message_id
        self.sender = sender
        self.chat = chat
        self.sender_id = getattr(sender, "id", None)
        self.action_log = action_log

    async def edit(self, text: str, **kwargs: object) -> None:
        if self.action_log is not None:
            self.action_log.append(f"edit:{self.id}")
        self.edits.append(text)

    async def delete(self) -> None:
        if self.action_log is not None:
            self.action_log.append(f"delete:{self.id}")
        self.deleted = True

    async def get_reply_message(self) -> "FakeMessage | None":
        return self._reply

    async def get_sender(self) -> object | None:
        return self.sender

    async def get_chat(self) -> object | None:
        return self.chat

    async def download_media(self, file: object = None) -> bytes:
        if self.action_log is not None:
            self.action_log.append(f"download:{self.id}")
        return self._media_bytes


class FakeEvent:
    def __init__(self, message: FakeMessage, history: list[FakeMessage] | None = None) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.client = self
        self.history = history
        self.sent_messages: list[dict[str, object]] = []
        self.action_log = message.action_log

    async def iter_messages(self, chat_id: int, limit: int, max_id: int | None = None, min_id: int | None = None):
        if self.history is not None:
            for item in self.history[:limit]:
                yield item
            return
        for index in range(limit):
            item = FakeMessage(f"history {index}", out=bool(index % 2))
            item.sender_id = 100 + index
            yield item

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> FakeMessage:
        if self.action_log is not None:
            self.action_log.append("send_message")
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return FakeMessage(text)


class StubAIReplyModule(AIReplyModule):
    async def _call_openai_responses_api(
        self,
        user_content: str,
        image_inputs: list[dict[str, str]],
    ) -> tuple[str, str, str, str]:
        return "回答内容", "", "Responses API × gpt-5.5", "Tokens | In: 1 | Out: 1 | Total: 2"


def test_extract_ai_prompt_matches_legacy_command_prefix() -> None:
    config = AIReplyConfig()

    assert extract_ai_prompt("/ai 你好", False, config) == "你好"
    assert extract_ai_prompt(".ai\n总结一下", False, config) == "总结一下"
    assert extract_ai_prompt("/ai", False, config) == ""


def test_extract_ai_prompt_matches_legacy_wake_and_reply_triggers() -> None:
    config = AIReplyConfig()

    assert extract_ai_prompt("问AI 这个是什么意思", False, config) == "这个是什么意思"
    assert extract_ai_prompt("回答", True, config) == ""
    assert extract_ai_prompt("回答 这句", True, config) == "这句"
    assert extract_ai_prompt("回答 这句", False, config) is None


def test_ai_reply_ignores_non_outgoing_messages() -> None:
    config = AIConfig(reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"))
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)

    result = asyncio.run(module.handle_message(FakeEvent(FakeMessage("/ai 你好", out=False))))

    assert result.status == "ignored"


def test_ai_reply_text_reply_embeds_quote_without_native_reply_target() -> None:
    config = AIConfig(reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"))
    module = StubAIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    replied = FakeMessage("被引用的内容", out=False, message_id=77)
    trigger = FakeMessage("回答 这是什么", is_reply=True, reply=replied, message_id=88)
    event = FakeEvent(trigger)

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert trigger.deleted is True
    assert event.sent_messages
    sent = event.sent_messages[0]
    assert "reply_to" not in sent
    assert "◔_◔ 引用消息" in str(sent["text"])
    assert "被引用的内容" in str(sent["text"])


def test_ai_reply_media_reply_keeps_native_reply_target() -> None:
    config = AIConfig(reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"))
    module = StubAIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    replied = FakeMessage("媒体说明", out=False, media=True, message_id=77)
    trigger = FakeMessage("回答 这是什么", is_reply=True, reply=replied, message_id=88)
    event = FakeEvent(trigger)

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert trigger.deleted is True
    assert event.sent_messages
    sent = event.sent_messages[0]
    assert sent["reply_to"] == 77
    assert "◔_◔ 引用消息" not in str(sent["text"])


def test_ai_reply_plain_trigger_deletes_before_media_collection() -> None:
    actions: list[str] = []
    original_collect = ai_reply_module.collect_image_inputs_for_responses

    async def fake_collect(event_or_message: object, prompt: str = "") -> tuple[list[dict[str, str]], str | None]:
        actions.append("collect_media")
        return [], None

    config = AIConfig(reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"))
    module = StubAIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    replied = FakeMessage("被引用的内容", out=False, media=True, message_id=77)
    trigger = FakeMessage("回答 这是什么", is_reply=True, reply=replied, message_id=88, action_log=actions)

    try:
        ai_reply_module.collect_image_inputs_for_responses = fake_collect
        result = asyncio.run(module.handle_message(FakeEvent(trigger)))
    finally:
        ai_reply_module.collect_image_inputs_for_responses = original_collect

    assert result.status == "handled"
    assert actions[:3] == ["delete:88", "send_message", "collect_media"]


def test_ai_setting_command_updates_runtime_settings(tmp_path: Path) -> None:
    config = AIConfig(
        reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"),
        reply=AIReplyConfig(settings_store=str(tmp_path / "ai_settings.json")),
    )
    message = FakeMessage("/ai_web off")
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert config.reply.web_search is False
    assert "web_search" in message.edits[-1]
    assert (tmp_path / "ai_settings.json").exists()


def test_msg_command_outputs_replied_user_and_message_info() -> None:
    config = AIConfig(reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"))
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    sender = SimpleNamespace(id=7613486483, first_name="Tester", username="tester", bot=False, premium=True)
    chat = SimpleNamespace(id=-1001, title="Test Group", username="test_group", megagroup=True)
    replied = FakeMessage("hello", out=False, sender=sender, chat=chat, message_id=77)
    trigger = FakeMessage("/msg", is_reply=True, reply=replied, message_id=88)
    event = FakeEvent(trigger)

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert trigger.deleted is True
    assert event.sent_messages
    sent = event.sent_messages[0]
    assert sent["reply_to"] == 77
    assert "<blockquote expandable>" in str(sent["text"])
    assert '"_": "Message"' in str(sent["text"])
    assert '"from_user"' in str(sent["text"])
    assert '"username": "tester"' in str(sent["text"])


def test_msg_command_respects_ai_reply_message_info_switch() -> None:
    config = AIConfig(
        reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"),
        reply=AIReplyConfig(message_info_enabled=False),
    )
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    replied = FakeMessage("hello", out=False, message_id=77)
    trigger = FakeMessage("/msg", is_reply=True, reply=replied, message_id=88)

    result = asyncio.run(module.handle_message(FakeEvent(trigger)))

    assert result.status == "ignored"
    assert trigger.deleted is False


def test_collect_short_context_includes_reply_text() -> None:
    reply = FakeMessage("被引用的内容")
    message = FakeMessage("回答", is_reply=True, reply=reply)

    context, reply_text = asyncio.run(collect_short_context(FakeEvent(message), AIReplyConfig(context_limit=2)))

    assert reply_text == "被引用的内容"
    assert "最近聊天上下文" in context
    assert "被回复的消息" in context


def test_collect_image_inputs_uses_all_album_images_by_default() -> None:
    album = [
        FakeMessage("", media=True, media_bytes=TINY_GIF_BYTES, grouped_id=7, message_id=index)
        for index in range(1, 4)
    ]
    message = FakeMessage("总结一下", is_reply=True, reply=album[0], message_id=20)

    image_inputs, error = asyncio.run(collect_image_inputs_for_responses(FakeEvent(message, album), "总结一下"))

    assert error is None
    assert [item["label"] for item in image_inputs] == ["引用图1", "引用图2", "引用图3"]
    assert all(item["url"].startswith("data:image/jpeg;base64,") for item in image_inputs)


def test_collect_image_inputs_respects_explicit_image_index() -> None:
    album = [
        FakeMessage("", media=True, media_bytes=TINY_GIF_BYTES, grouped_id=7, message_id=index)
        for index in range(1, 4)
    ]
    message = FakeMessage("总结图二", is_reply=True, reply=album[0], message_id=20)

    image_inputs, error = asyncio.run(collect_image_inputs_for_responses(FakeEvent(message, album), "总结图二"))

    assert error is None
    assert [item["label"] for item in image_inputs] == ["引用图2"]


def test_extract_requested_image_indexes() -> None:
    assert extract_requested_image_indexes("只看图2和第四张") == {2, 4}
    assert extract_requested_image_indexes("总结一下") == set()


def test_ai_reply_footer_keeps_usage_lines_together() -> None:
    rendered = format_ai_group_message(
        "问题",
        "答案",
        "gpt-5.5",
        answer_is_html=False,
        powered_by="Responses API × gpt-5.5",
        token_stats="Tokens | In: 3627 | Out: 181 | Total: 3808",
        elapsed_seconds=17.84,
    )

    assert "🚀 Responses API × gpt-5.5</i>\n<i>📊 Tokens | In: 3627 | Out: 181 | Total: 3808</i>" in rendered
    assert "<i>⏱️ Time: 17.8s</i>" in rendered
    assert "<i>⏱️ Time: 17.8s</i>\n\n◆ 当前模型" in rendered
    assert "Responses API × gpt-5.5</i>\n\n<i>📊 Tokens" not in rendered


def test_representative_frame_positions_spread_across_motion_media() -> None:
    assert representative_frame_positions(0, 3) == [0.0, 1.0, 2.0]
    positions = representative_frame_positions(60, 6)
    assert len(positions) == 6
    assert positions[0] > 0
    assert positions[-1] < 60
    assert positions == sorted(positions)


def test_telegram_webm_sticker_without_filename_is_motion_media() -> None:
    message = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="video/webm",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext="", mime_type=""),
    )

    assert media_file_suffix(message) == ".webm"
    assert media_is_motion(message) is True
    assert media_may_be_video(message) is True


def test_telegram_file_ext_fallback_detects_webm_sticker() -> None:
    message = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext=".webm", mime_type=""),
    )

    assert media_file_suffix(message) == ".webm"
    assert media_is_motion(message) is True


def test_tgs_sticker_is_recognized_but_not_sent_to_ffmpeg() -> None:
    message = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="application/x-tgsticker",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext="", mime_type=""),
    )

    assert media_file_suffix(message) == ".tgs"
    assert media_is_tgs_sticker(message) is True
    assert media_is_motion(message) is False
    assert media_may_be_video(message) is False


def test_ai_setting_command_blocked_for_non_owner(tmp_path: Path) -> None:
    config = AIConfig(
        reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"),
        reply=AIReplyConfig(owner_user_ids=[999], settings_store=str(tmp_path / "owner.json")),
    )
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    message = FakeMessage("/ai_web off")
    message.sender_id = 7  # 非 owner

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "ignored"
    assert config.reply.web_search is True


def test_ai_setting_command_allowed_for_owner(tmp_path: Path) -> None:
    config = AIConfig(
        reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"),
        reply=AIReplyConfig(owner_user_ids=[999], settings_store=str(tmp_path / "owner.json")),
    )
    module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
    message = FakeMessage("/ai_web off")
    message.sender_id = 999  # owner

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert config.reply.web_search is False


def test_ai_reply_temperature_only_for_non_reasoning_model(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            captured.clear()
            captured.update(kwargs)
            return SimpleNamespace(status="completed", incomplete_details={}, output=[], output_text="ok", usage=None)

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            pass

    original = ai_reply_module.AsyncOpenAI
    try:
        ai_reply_module.AsyncOpenAI = FakeOpenAI

        non_reasoning = AIConfig(
            reply_provider=AIProviderConfig(enabled=True, model="gpt-4o", api_key="x"),
            reply=AIReplyConfig(temperature=0.42, settings_store=str(tmp_path / "t1.json")),
        )
        module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), non_reasoning)
        asyncio.run(module._call_openai_responses_api("hi", []))
        assert captured.get("temperature") == 0.42

        reasoning = AIConfig(
            reply_provider=AIProviderConfig(enabled=True, model="gpt-5.5", api_key="x"),
            reply=AIReplyConfig(temperature=0.42, settings_store=str(tmp_path / "t2.json")),
        )
        module2 = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), reasoning)
        asyncio.run(module2._call_openai_responses_api("hi", []))
        assert "temperature" not in captured
    finally:
        ai_reply_module.AsyncOpenAI = original


def test_ai_reply_chat_completions_channel_uses_chat_payload(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="可用回答", reasoning=""),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self) -> None:
            captured["closed"] = True

    config = AIConfig(
        reply_provider=AIProviderConfig(
            provider_type="openai-compatible-chat",
            base_url="http://sub2api.example/v1",
            api_key="test-key",
            model="gpt-5.6-sol",
            enabled=True,
        ),
        reply=AIReplyConfig(
            max_tokens=321,
            web_search=True,
            reasoning_effort="none",
            image_detail="original",
            settings_store=str(tmp_path / "chat.json"),
        ),
    )
    original = ai_reply_module.AsyncOpenAI
    try:
        ai_reply_module.AsyncOpenAI = FakeOpenAI
        module = AIReplyModule(ModuleCard("ai_reply", "AI", "", "ai", enabled=True), config)
        answer, reasoning, powered_by, usage = asyncio.run(
            module._call_openai_chat_completions_api(
                "请看图",
                [{"label": "引用图1", "url": "data:image/png;base64,AAAB"}],
            )
        )
    finally:
        ai_reply_module.AsyncOpenAI = original

    request = captured["request"]
    assert isinstance(request, dict)
    assert request["model"] == "gpt-5.6-sol"
    assert request["max_tokens"] == 321
    assert "max_output_tokens" not in request
    assert "tools" not in request
    assert "include" not in request
    assert request["messages"][-1]["content"][-1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAB", "detail": "auto"},
    }
    assert answer == "可用回答"
    assert reasoning == ""
    assert powered_by == "Chat Completions API + Vision × gpt-5.6-sol"
    assert "Total: 15" in usage
    assert captured["closed"] is True
