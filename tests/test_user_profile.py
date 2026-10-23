from __future__ import annotations

import asyncio
import html
import re
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from telegram_bot.config import AIConfig, AIProviderConfig, ChatHistoryConfig, TelegramConfig, UserProfileConfig
from telegram_bot.modules import user_profile as user_profile_module
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.user_profile import (
    ProfileCommand,
    ProfileSample,
    UserProfileModule,
    build_message_link,
    build_profile_prompt,
    build_profile_rich_message,
    extract_profile_command,
    normalize_profile_result,
    render_profile_html,
    render_profile_rich_markdown,
)
from telegram_bot.persistence import ChatHistoryStore


def _sample(message_id: int, text: str, *, kind: str = "text") -> ProfileSample:
    return ProfileSample(
        message_id=message_id,
        date=datetime(2026, 7, min(message_id, 28), tzinfo=timezone.utc),
        text=text,
        kind=kind,
        link=f"https://t.me/c/0000000001/{message_id}",
    )


def test_profile_command_supports_reply_and_username_forms() -> None:
    config = UserProfileConfig()

    assert extract_profile_command("/profile", False, config) == ProfileCommand(target_ref="", sample_size=40)
    assert extract_profile_command("/profile 80", True, config) == ProfileCommand(target_ref="", sample_size=80)
    assert extract_profile_command("/profile @nkr_404 60", False, config) == ProfileCommand(target_ref="@nkr_404", sample_size=60)
    assert extract_profile_command("画像 @nkr_404", False, config) == ProfileCommand(target_ref="@nkr_404", sample_size=40)
    assert extract_profile_command("/profiles @nkr_404", False, config) is None

    large_config = UserProfileConfig(max_sample_size=2000)
    assert extract_profile_command("/profile 2000", True, large_config) == ProfileCommand(target_ref="", sample_size=2000)
    assert extract_profile_command("/profile 9999", True, large_config) == ProfileCommand(target_ref="", sample_size=2000)
    assert extract_profile_command("/fx all", True, config) == ProfileCommand(
        target_ref="",
        sample_size=40,
        all_history=True,
        history_scope="all",
    )
    assert extract_profile_command(".fx @nkr_404 all", False, config) == ProfileCommand(
        target_ref="@nkr_404",
        sample_size=40,
        all_history=True,
        history_scope="all",
    )
    assert extract_profile_command("/fx local", True, config) == ProfileCommand(
        target_ref="",
        sample_size=40,
        all_history=True,
        history_scope="local",
    )


def test_private_group_message_link_uses_telegram_internal_chat_id() -> None:
    assert build_message_link(-1000000000001, 1772468) == "https://t.me/c/0000000001/1772468"
    assert build_message_link(-1000000000001, 1772468, "public_group") == "https://t.me/public_group/1772468"
    assert build_message_link(-12345, 10) == ""


def test_profile_result_drops_fake_evidence_and_uses_real_quote_text() -> None:
    samples = [_sample(10, "nest 我大哥"), _sample(11, "<b>头像真好看</b>")]
    raw = {
        "tagline": "贴纸和短句型气氛组",
        "personality": [
            {"title": "短句刺客", "analysis": "一句话就能制造笑点", "evidence_ids": [10, 999]},
        ],
        "interests": [{"topic": "头像", "detail": "对好看的头像格外敏感"}],
        "quotes": [{"message_id": 11, "text": "AI 伪造的原文", "comment": "颜控现场"}],
        "verdict": ["群聊润滑剂"],
        "closing": "不制造信息，只制造存在感。",
    }

    result = normalize_profile_result(raw, samples)

    assert result.personality[0].evidence_ids == [10]
    assert result.quotes[0].text == "<b>头像真好看</b>"


def test_profile_renderer_is_expandable_escaped_and_linked() -> None:
    samples = [_sample(10, "nest 我大哥"), _sample(11, "<b>头像真好看</b>")]
    result = normalize_profile_result(
        {
            "tagline": "话少但存在感强",
            "personality": [{"title": "短句刺客", "analysis": "用 <tag> 刷存在感", "evidence_ids": [10]}],
            "interests": ["头像与贴纸"],
            "quotes": [{"message_id": 11, "comment": "颜控现场"}],
            "verdict": ["气氛润滑剂"],
            "closing": "可爱的活跃水怪",
        },
        samples,
    )

    rendered = render_profile_html(
        result,
        target_label="@nkr_404_not_found",
        samples=samples,
        model="deepseek-v4-flash",
        total_tokens=3842,
    )

    assert "<b>👤 用户画像：@nkr_404_not_found</b>" in rendered
    assert "<blockquote expandable>" in rendered
    assert "🧩 <b>性格速写</b>" in rendered
    assert "&lt;tag&gt;" in rendered
    assert "&lt;b&gt;头像真好看&lt;/b&gt;" in rendered
    assert "https://t.me/c/0000000001/10" in rendered
    assert "https://t.me/c/0000000001/11" in rendered
    assert "Powered by deepseek-v4-flash ｜ 3,842 tokens" in rendered


def test_profile_rich_markdown_renders_native_tables_details_and_links() -> None:
    samples = [_sample(10, "nest | 我大哥"), _sample(11, "头像真好看")]
    result = normalize_profile_result(
        {
            "tagline": "话少但存在感强",
            "personality": [{"title": "短句刺客", "analysis": "用短句刷存在感", "evidence_ids": [10]}],
            "interests": [{"topic": "头像 | 贴纸", "detail": "经常索要好看的头像"}],
            "quotes": [{"message_id": 11, "comment": "颜控现场"}],
            "ratings": [{"dimension": "气氛感", "score": 9, "comment": "稳定参与群聊"}],
            "verdict": ["气氛润滑剂"],
            "closing": "可爱的活跃水怪",
        },
        samples,
    )

    rendered = render_profile_rich_markdown(
        result,
        target_label="@nkr_404_not_found",
        samples=samples,
        model="deepseek-v4-flash",
        total_tokens=3842,
    )

    assert r"# 👤 用户画像：@nkr\_404\_not\_found" in rendered
    assert "<details open><summary>点击展开详情</summary>" in rendered
    assert "| 领域 | 证据与表现 |" in rendered
    assert "头像 \\| 贴纸" in rendered
    assert "| 维度 | 评分 | 点评 |" in rendered
    assert "⭐⭐⭐⭐⭐" in rendered
    assert "[↗](https://t.me/c/0000000001/10)" in rendered
    assert "Powered by deepseek-v4-flash ｜ 3,842 tokens" in rendered


def test_profile_explicit_rich_blocks_render_tables_for_user_accounts() -> None:
    class FakeRichNode:
        def __init__(self, kind: str, values: dict[str, object]) -> None:
            self.kind = kind
            self.values = values

    def fake_type(kind: str):
        return lambda **values: FakeRichNode(kind, values)

    rich_types = SimpleNamespace(
        InputRichMessage=fake_type("InputRichMessage"),
        PageBlockTitle=fake_type("PageBlockTitle"),
        PageBlockParagraph=fake_type("PageBlockParagraph"),
        PageBlockBlockquote=fake_type("PageBlockBlockquote"),
        PageBlockDetails=fake_type("PageBlockDetails"),
        PageBlockHeader=fake_type("PageBlockHeader"),
        PageBlockSubheader=fake_type("PageBlockSubheader"),
        PageBlockTable=fake_type("PageBlockTable"),
        PageTableRow=fake_type("PageTableRow"),
        PageTableCell=fake_type("PageTableCell"),
        PageBlockFooter=fake_type("PageBlockFooter"),
        TextEmpty=fake_type("TextEmpty"),
        TextPlain=fake_type("TextPlain"),
        TextBold=fake_type("TextBold"),
        TextItalic=fake_type("TextItalic"),
        TextConcat=fake_type("TextConcat"),
        TextUrl=fake_type("TextUrl"),
    )
    samples = [_sample(10, "nest 我大哥"), _sample(11, "头像真好看")]
    result = normalize_profile_result(
        {
            "tagline": "话少但存在感强",
            "personality": [{"title": "短句刺客", "analysis": "用短句刷存在感", "evidence_ids": [10]}],
            "interests": [{"topic": "头像与贴纸", "detail": "经常索要好看的头像"}],
            "quotes": [{"message_id": 11, "comment": "颜控现场"}],
            "ratings": [{"dimension": "气氛感", "score": 5, "comment": "稳定参与群聊"}],
            "verdict": ["气氛润滑剂"],
            "closing": "可爱的活跃水怪",
        },
        samples,
    )

    rich_message = build_profile_rich_message(
        result,
        target_label="@nkr_404_not_found",
        samples=samples,
        model="deepseek-v4-flash",
        total_tokens=3842,
        rich_types=rich_types,
    )

    def walk(value: object):
        if isinstance(value, FakeRichNode):
            yield value
            for child in value.values.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    nodes = list(walk(rich_message))
    plain_text = [node.values["text"] for node in nodes if node.kind == "TextPlain"]
    urls = [node.values["url"] for node in nodes if node.kind == "TextUrl"]
    tables = [node for node in nodes if node.kind == "PageBlockTable"]

    assert rich_message.kind == "InputRichMessage"
    assert rich_message.values["noautolink"] is True
    assert len(tables) == 2
    assert all(table.values["bordered"] is True and table.values["striped"] is True for table in tables)
    assert "领域" in plain_text and "证据与表现" in plain_text
    assert "维度" in plain_text and "评分" in plain_text and "点评" in plain_text
    assert "⭐⭐⭐⭐⭐" in plain_text
    assert "https://t.me/c/0000000001/10" in urls
    assert "https://t.me/c/0000000001/11" in urls


def test_profile_rich_message_uses_telethon_raw_edit_request() -> None:
    class FakeInputRichMessageMarkdown:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeEditMessageRequest:
        def __init__(self, *, peer: object, id: int, message: str, rich_message: object) -> None:
            self.kwargs = {
                "peer": peer,
                "id": id,
                "message": message,
                "rich_message": rich_message,
            }

    telethon = ModuleType("telethon")
    telethon.types = SimpleNamespace(InputRichMessageMarkdown=FakeInputRichMessageMarkdown)
    telethon.functions = SimpleNamespace(messages=SimpleNamespace(EditMessageRequest=FakeEditMessageRequest))

    class RichClient:
        def __init__(self) -> None:
            self.request: FakeEditMessageRequest | None = None

        async def get_input_entity(self, chat_id: int) -> str:
            assert chat_id == -1000000000001
            return "input-peer"

        async def __call__(self, request: FakeEditMessageRequest) -> None:
            self.request = request

    client = RichClient()
    event = SimpleNamespace(client=client, chat_id=-1000000000001)
    message = SimpleNamespace(id=99, chat_id=-1000000000001)
    module = UserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(),
        AIConfig(),
    )

    with patch.dict(sys.modules, {"telethon": telethon}):
        edited = asyncio.run(module._try_edit_profile_rich_message(event, message, "| A | B |"))

    assert edited is True
    assert client.request is not None
    assert client.request.kwargs["peer"] == "input-peer"
    assert client.request.kwargs["id"] == 99
    assert client.request.kwargs["message"] == ""
    assert client.request.kwargs["rich_message"].kwargs["markdown"] == "| A | B |"


def test_profile_rich_message_logs_outdated_telethon_before_html_fallback() -> None:
    class OldEditMessageRequest:
        def __init__(self, *, peer: object, id: int, message: str) -> None:
            self.peer = peer
            self.id = id
            self.message = message

    telethon = ModuleType("telethon")
    telethon.__version__ = "1.43.2"
    telethon.types = SimpleNamespace()
    telethon.functions = SimpleNamespace(messages=SimpleNamespace(EditMessageRequest=OldEditMessageRequest))

    class RichClient:
        async def get_input_entity(self, chat_id: int) -> str:
            return "input-peer"

        async def __call__(self, request: object) -> None:
            raise AssertionError("outdated Telethon must not send a rich request")

    module = UserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(),
        AIConfig(),
    )
    event = SimpleNamespace(client=RichClient(), chat_id=-1000000000001)
    message = SimpleNamespace(id=99, chat_id=-1000000000001)

    with (
        patch.object(user_profile_module.logger, "warning") as warning,
        patch.dict(sys.modules, {"telethon": telethon}),
    ):
        edited = asyncio.run(module._try_edit_profile_rich_message(event, message, "| A | B |"))

    assert edited is False
    assert any(
        "telethon_version=%s" in call.args[0]
        and "has_markdown_type=False" in call.args[0]
        and "1.43.2" in call.args
        for call in warning.call_args_list
    )


def test_profile_rejects_sensitive_attribute_inference_before_rendering() -> None:
    samples = [_sample(10, "最近好累")]
    raw = {
        "tagline": "他可能患有抑郁症",
        "personality": [{"title": "安静", "analysis": "话很少", "evidence_ids": [10]}],
        "interests": ["日常聊天"],
        "quotes": [{"message_id": 10, "comment": "近期状态"}],
        "verdict": ["低调"],
        "closing": "仅代表当前样本",
    }

    try:
        normalize_profile_result(raw, samples)
    except ValueError as exc:
        assert "敏感属性推断" in str(exc)
    else:
        raise AssertionError("敏感属性推断应在渲染前被拒绝")


def test_profile_renderer_keeps_extreme_escaped_output_within_safe_budget() -> None:
    samples = [_sample(message_id, "<&" * 300) for message_id in range(1, 101)]
    raw = {
        "tagline": "<&" * 500,
        "personality": [
            {"title": "<&" * 100, "analysis": "<&" * 500, "evidence_ids": [1, 2, 3]}
            for _ in range(5)
        ],
        "interests": [{"topic": "<&" * 100, "detail": "<&" * 500} for _ in range(6)],
        "quotes": [{"message_id": item, "comment": "<&" * 300} for item in range(1, 6)],
        "verdict": ["<&" * 300 for _ in range(6)],
        "closing": "<&" * 500,
    }

    rendered = render_profile_html(
        normalize_profile_result(raw, samples),
        target_label="@" + "u" * 32,
        samples=samples,
        model="model-" + "x" * 80,
        total_tokens=999999,
    )
    visible = html.unescape(re.sub(r"<[^>]+>", "", rendered))

    assert len(rendered) <= 4000
    assert len(visible) <= 3600
    assert rendered.endswith("</i>")
    assert rendered.count("<blockquote") == rendered.count("</blockquote>")


def test_profile_prompt_contains_statistics_and_safety_boundary() -> None:
    samples = [_sample(10, "hello"), _sample(11, "[贴纸]", kind="sticker")]

    prompt = build_profile_prompt("@someone", samples, UserProfileConfig())

    assert "样本数：2" in prompt
    assert "贴纸" in prompt
    assert '"evidence_ids"' in prompt
    assert "不得推断" in prompt


def test_profile_prompt_uses_large_sample_statistics_with_bounded_evidence_payload() -> None:
    samples = [_sample(message_id, "长消息" * 240) for message_id in range(1, 2001)]

    prompt_samples = user_profile_module.select_profile_prompt_samples(samples)
    prompt = build_profile_prompt("@large_history", samples, UserProfileConfig(), prompt_samples)

    assert "样本数：2000" in prompt
    assert f"提供给模型的代表性消息：{len(prompt_samples)} 条" in prompt
    assert prompt_samples[0].message_id == 1
    assert prompt_samples[-1].message_id == 2000
    assert len(prompt_samples) < len(samples)
    assert len(prompt) <= 105_000


def test_all_history_chunks_keep_every_message_and_full_text() -> None:
    samples = [_sample(message_id, f"消息 {message_id} " + "长文本" * 80) for message_id in range(1, 31)]

    chunks = user_profile_module.chunk_profile_samples(samples, max_chars=2000)
    flattened = [sample for chunk in chunks for sample in chunk]

    assert len(chunks) > 1
    assert [sample.message_id for sample in flattened] == list(range(1, 31))
    assert [sample.text for sample in flattened] == [sample.text for sample in samples]


def test_profile_chat_completions_channel_avoids_responses_fields() -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"tagline":"简短","personality":[],"interests":[],'
                                '"quotes":[],"verdict":[],"closing":"完成"}'
                            )
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self) -> None:
            captured["closed"] = True

    original = user_profile_module.AsyncOpenAI
    try:
        user_profile_module.AsyncOpenAI = FakeOpenAI
        module = UserProfileModule(
            ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
            UserProfileConfig(max_tokens=4000),
            AIConfig(
                reply_provider=AIProviderConfig(
                    provider_type="openai-compatible-chat",
                    base_url="http://sub2api.example/v1",
                    api_key="test-key",
                    model="gpt-5.6-sol",
                )
            ),
        )
        module._record_ai_usage = lambda *args, **kwargs: None
        result, total_tokens = asyncio.run(module._generate_profile("画像输入"))
    finally:
        user_profile_module.AsyncOpenAI = original

    request = captured["request"]
    assert isinstance(request, dict)
    assert request["max_tokens"] == 4000
    assert "max_output_tokens" not in request
    assert request["messages"][0]["role"] == "system"
    assert result["tagline"] == "简短"
    assert total_tokens == 30
    assert captured["closed"] is True


def test_profile_module_reply_flow_sends_html_result() -> None:
    target = SimpleNamespace(id=88, username="nkr_404_not_found", first_name="Nkr", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    history = [
        FakeMessage(f"消息 {index}", message_id=index, sender_id=88, sender=target, out=False)
        for index in range(1, 11)
    ]
    event = FakeEvent(command, history)
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(
            min_required_samples=3,
            min_sample_size=3,
            default_sample_size=10,
            delete_command=True,
        ),
        AIConfig(),
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert command.deleted is False
    assert event.client.sent == []
    assert "画像分析中" in command.edits[0]["text"]
    assert "正在识别目标群友" in command.edits[0]["text"]
    assert "正在读取" in command.edits[1]["text"]
    assert "已读取 10 条有效样本" in command.edits[2]["text"]
    assert "正在请求" in command.edits[2]["text"]
    assert command.edits[-1]["parse_mode"] == "html"
    assert "用户画像：@nkr_404_not_found" in command.edits[-1]["text"]
    assert event.client.iter_kwargs["from_user"] == 88


def test_profile_rich_edit_rejection_sends_new_rich_message_and_deletes_status() -> None:
    class FakeInputRichMessageMarkdown:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeEditMessageRequest:
        def __init__(self, *, peer: object, id: int, message: str, rich_message: object) -> None:
            self.rich_message = rich_message

    class FakeSendMessageRequest:
        def __init__(
            self,
            *,
            peer: object,
            message: str,
            random_id: int,
            rich_message: object,
        ) -> None:
            self.peer = peer
            self.message = message
            self.random_id = random_id
            self.rich_message = rich_message

    telethon = ModuleType("telethon")
    telethon.__version__ = "1.44.0"
    telethon.types = SimpleNamespace(InputRichMessageMarkdown=FakeInputRichMessageMarkdown)
    telethon.functions = SimpleNamespace(
        messages=SimpleNamespace(
            EditMessageRequest=FakeEditMessageRequest,
            SendMessageRequest=FakeSendMessageRequest,
        )
    )

    class RichFallbackClient(FakeClient):
        def __init__(self, history: list[FakeMessage]) -> None:
            super().__init__(history)
            self.raw_requests: list[object] = []

        async def get_input_entity(self, chat_id: int) -> str:
            assert chat_id == -1000000000001
            return "input-peer"

        async def __call__(self, request: object) -> None:
            self.raw_requests.append(request)
            if isinstance(request, FakeEditMessageRequest):
                raise RuntimeError("RICH_MESSAGE_UNSUPPORTED")

    target = SimpleNamespace(id=88, username="rich_user", first_name="Rich", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    history = [
        FakeMessage(f"消息 {index}", message_id=index, sender_id=88, sender=target, out=False)
        for index in range(1, 11)
    ]
    event = FakeEvent(command, history)
    event.client = RichFallbackClient(history)
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3, min_sample_size=3, default_sample_size=10),
        AIConfig(),
    )

    with (
        patch.dict(sys.modules, {"telethon": telethon}),
        patch.object(user_profile_module.logger, "info") as info,
    ):
        result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert [type(request) for request in event.client.raw_requests] == [
        FakeEditMessageRequest,
        FakeSendMessageRequest,
    ]
    sent_request = event.client.raw_requests[-1]
    assert sent_request.peer == "input-peer"
    assert sent_request.message == ""
    assert sent_request.random_id > 0
    assert sent_request.rich_message.kwargs["markdown"].startswith("# 👤 用户画像")
    assert command.deleted is True
    assert event.client.sent == []
    assert all("用户画像：@rich_user" not in edit["text"] for edit in command.edits)
    assert any(
        call.args[0].startswith("User profile analysis completed:")
        and call.args[-1] == "rich_markdown_send"
        for call in info.call_args_list
    )


def test_profile_rich_send_rejection_still_falls_back_to_html_edit() -> None:
    class FakeInputRichMessageMarkdown:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeEditMessageRequest:
        def __init__(self, *, peer: object, id: int, message: str, rich_message: object) -> None:
            self.rich_message = rich_message

    class FakeSendMessageRequest:
        def __init__(
            self,
            *,
            peer: object,
            message: str,
            random_id: int,
            rich_message: object,
        ) -> None:
            self.rich_message = rich_message

    telethon = ModuleType("telethon")
    telethon.__version__ = "1.44.0"
    telethon.types = SimpleNamespace(InputRichMessageMarkdown=FakeInputRichMessageMarkdown)
    telethon.functions = SimpleNamespace(
        messages=SimpleNamespace(
            EditMessageRequest=FakeEditMessageRequest,
            SendMessageRequest=FakeSendMessageRequest,
        )
    )

    class RejectingRichClient(FakeClient):
        async def get_input_entity(self, chat_id: int) -> str:
            return "input-peer"

        async def __call__(self, request: object) -> None:
            raise RuntimeError("RICH_MESSAGE_UNSUPPORTED")

    target = SimpleNamespace(id=88, username="html_user", first_name="Html", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    history = [
        FakeMessage(f"消息 {index}", message_id=index, sender_id=88, sender=target, out=False)
        for index in range(1, 11)
    ]
    event = FakeEvent(command, history)
    event.client = RejectingRichClient(history)
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3, min_sample_size=3, default_sample_size=10),
        AIConfig(),
    )

    with patch.dict(sys.modules, {"telethon": telethon}):
        result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert command.deleted is False
    assert command.edits[-1]["parse_mode"] == "html"
    assert "用户画像：@html_user" in command.edits[-1]["text"]


def test_profile_generation_has_total_timeout_and_updates_status() -> None:
    target = SimpleNamespace(id=88, username="slow_user", first_name="Slow", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    history = [
        FakeMessage(f"消息 {index}", message_id=index, sender_id=88, sender=target, out=False)
        for index in range(1, 11)
    ]
    event = FakeEvent(command, history)
    module = SlowUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(
            min_required_samples=3,
            min_sample_size=3,
            default_sample_size=10,
            timeout_seconds=0.01,
        ),
        AIConfig(),
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert command.deleted is False
    assert "已读取 10 条有效样本" in command.edits[-2]["text"]
    assert "AI 分析超过 0.01 秒" in command.edits[-1]["text"]


def test_profile_uses_database_history_before_telegram_fallback(tmp_path) -> None:
    target = SimpleNamespace(id=88, username="archived_user", first_name="Archived", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    event = FakeEvent(command, [])
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    for message_id in range(1, 11):
        archived = FakeMessage(
            f"数据库消息 {message_id}",
            message_id=message_id,
            sender_id=88,
            sender=target,
            out=False,
        )
        store.record_event(SimpleNamespace(message=archived, chat_id=archived.chat_id, sender_id=88))

    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3, min_sample_size=3, default_sample_size=10),
        AIConfig(),
        tmp_path,
        store,
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert event.client.iter_kwargs == {}
    assert module.card.metrics["last_sample_count"] == 10
    assert "用户画像：@archived_user" in command.edits[-1]["text"]
    store.close()


def test_fx_all_analyzes_more_than_two_thousand_messages_across_monitored_chats(tmp_path) -> None:
    target = SimpleNamespace(id=88, username="all_history_user", first_name="All", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/fx all", message_id=9999, sender_id=1, out=True, reply=replied)
    event = FakeEvent(command, [])
    store = ChatHistoryStore(
        ChatHistoryConfig(database_path=str(tmp_path / "chat-history.sqlite3")),
        tmp_path,
    )
    archived = [
        FakeMessage(
            f"数据库历史消息 {message_id}",
            message_id=message_id,
            sender_id=88,
            sender=target,
            out=False,
        )
        for message_id in range(1, 2106)
    ]
    assert store.record_events(archived) == 2105
    other_chat_id = -1000000000003
    other_chat_messages = [
        FakeMessage(
            f"另一个群的消息 {message_id}",
            message_id=message_id,
            sender_id=88,
            sender=target,
            out=False,
        )
        for message_id in range(1, 4)
    ]
    for item in other_chat_messages:
        item.chat_id = other_chat_id
    assert store.record_events(other_chat_messages) == 3
    store.mark_backfill_complete(command.chat_id, 2105)
    store.mark_backfill_complete(other_chat_id, 3)
    telegram_config = TelegramConfig(
        monitored_groups=[str(command.chat_id), str(other_chat_id)],
        monitored_group_meta={
            str(command.chat_id): {"title": "当前群", "username": "", "kind": "group"},
            str(other_chat_id): {"title": "另一个群", "username": "", "kind": "group"},
        },
    )
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3),
        AIConfig(),
        tmp_path,
        store,
        telegram_config,
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert event.client.iter_kwargs == {}
    assert module.card.metrics["last_sample_count"] == 2108
    assert "样本 2108 条" in command.edits[-1]["text"]
    assert "跨群" in command.edits[-1]["text"]
    assert "所有历史消息均已分析" in command.edits[-2]["text"]
    store.close()


def test_fx_local_only_uses_current_chat_archive(tmp_path) -> None:
    target = SimpleNamespace(id=88, username="local_user", first_name="Local", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FakeMessage("/fx local", message_id=9999, sender_id=1, out=True, reply=replied)
    event = FakeEvent(command, [])
    other_chat_id = -1000000000003
    store = ChatHistoryStore(ChatHistoryConfig(database_path=str(tmp_path / "chat.sqlite3")), tmp_path)
    current = [FakeMessage(f"本群 {item}", message_id=item, sender_id=88, sender=target, out=False) for item in range(1, 11)]
    other = [FakeMessage(f"他群 {item}", message_id=item, sender_id=88, sender=target, out=False) for item in range(1, 11)]
    for item in other:
        item.chat_id = other_chat_id
    store.record_events(current)
    store.record_events(other)
    store.mark_backfill_complete(command.chat_id, 10)
    store.mark_backfill_complete(other_chat_id, 10)
    telegram_config = TelegramConfig(monitored_groups=[str(command.chat_id), str(other_chat_id)])
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3),
        AIConfig(),
        tmp_path,
        store,
        telegram_config,
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert module.card.metrics["last_sample_count"] == 10
    assert "样本 10 条" in command.edits[-1]["text"]
    assert "本群" in command.edits[-1]["text"]
    store.close()


def test_profile_final_edit_failure_sends_result_as_fallback() -> None:
    target = SimpleNamespace(id=88, username="fallback_user", first_name="Fallback", last_name="")
    replied = FakeMessage("hello", message_id=2, sender_id=88, sender=target, out=False)
    command = FinalEditFailingMessage("/profile 10", message_id=99, sender_id=1, out=True, reply=replied)
    history = [
        FakeMessage(f"消息 {index}", message_id=index, sender_id=88, sender=target, out=False)
        for index in range(1, 11)
    ]
    event = FakeEvent(command, history)
    module = StubUserProfileModule(
        ModuleCard("user_profile", "群友画像", "", "ai", enabled=True),
        UserProfileConfig(min_required_samples=3, min_sample_size=3, default_sample_size=10),
        AIConfig(),
    )

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert event.client.sent
    assert "用户画像：@fallback_user" in event.client.sent[-1].raw_text


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        message_id: int,
        sender_id: int,
        sender: object | None = None,
        out: bool,
        reply: object | None = None,
    ) -> None:
        self.raw_text = text
        self.text = text
        self.message = text
        self.id = message_id
        self.chat_id = -1000000000001
        self.sender_id = sender_id
        self.sender = sender
        self.out = out
        self.is_reply = reply is not None
        self._reply = reply
        self.date = datetime(2026, 7, min(max(message_id, 1), 28), tzinfo=timezone.utc)
        self.media = None
        self.sticker = None
        self.photo = None
        self.video = None
        self.voice = None
        self.gif = None
        self.deleted = False
        self.edits: list[dict[str, object]] = []

    async def get_reply_message(self) -> object | None:
        return self._reply

    async def get_sender(self) -> object | None:
        return self.sender

    async def delete(self) -> None:
        self.deleted = True

    async def edit(self, text: str, **kwargs: object) -> None:
        self.edits.append({"text": text, **kwargs})


class FinalEditFailingMessage(FakeMessage):
    async def edit(self, text: str, **kwargs: object) -> None:
        if "用户画像：" in text:
            raise RuntimeError("final edit failed")
        await super().edit(text, **kwargs)


class FakeClient:
    def __init__(self, history: list[FakeMessage]) -> None:
        self.history = history
        self.sent: list[FakeMessage] = []
        self.iter_kwargs: dict[str, object] = {}

    async def iter_messages(self, chat_id: int, **kwargs: object):
        self.iter_kwargs = {"chat_id": chat_id, **kwargs}
        target = kwargs.get("from_user")
        target_id = getattr(target, "id", target)
        for message in reversed(self.history):
            if message.sender_id == target_id:
                yield message

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> FakeMessage:
        message = FakeMessage(text, message_id=500 + len(self.sent), sender_id=1, out=True)
        message.send_kwargs = {"chat_id": chat_id, **kwargs}
        self.sent.append(message)
        return message


class FakeEvent:
    def __init__(self, message: FakeMessage, history: list[FakeMessage]) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.out = message.out
        self.client = FakeClient(history)
        self.chat = SimpleNamespace(username=None)


class StubUserProfileModule(UserProfileModule):
    async def _generate_profile(self, prompt: str):
        return (
            {
                "tagline": "用短句维持群聊存在感。",
                "personality": [{"title": "短句刺客", "analysis": "言简意赅", "evidence_ids": [1]}],
                "interests": ["日常闲聊"],
                "quotes": [{"message_id": 1, "comment": "代表性开场"}],
                "verdict": ["群聊气氛组"],
                "closing": "存在感稳定。",
            },
            321,
        )


class SlowUserProfileModule(UserProfileModule):
    async def _generate_profile(self, prompt: str):
        await asyncio.sleep(1)
        raise AssertionError("AI call should have been cancelled by the total timeout")

    def _record_ai_usage(self, *args: object, **kwargs: object) -> None:
        return None
