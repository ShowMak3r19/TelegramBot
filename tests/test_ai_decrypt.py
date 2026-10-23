from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.config import AIConfig, AIDecryptConfig, AIDecryptTemplateConfig, AIProviderConfig, AppConfig
import telegram_bot.modules.ai_decrypt as ai_decrypt_module
from telegram_bot.modules.ai_decrypt import AIDecryptModule, sanitize_answer
from telegram_bot.modules.base import ModuleCard

TINY_GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01L\x00;"


class FakeMessage:
    def __init__(self, text: str, *, message_id: int = 1, media: bool = True) -> None:
        self.raw_text = text
        self.media = object() if media else None
        self.id = message_id
        self.chat_id = -1001
        self.responses: list[str] = []

    async def respond(self, text: str) -> None:
        self.responses.append(text)

    async def download_media(self, file: object = None) -> bytes:
        return TINY_GIF_BYTES


class FakeEvent:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.chat_id = message.chat_id


def test_ai_decrypt_dice_template_sends_solver_answer() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        module = AIDecryptModule(
            ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
            AIDecryptConfig(
                templates=[
                    AIDecryptTemplateConfig(
                        id="dice",
                        trigger_keywords=["九宫格骰子竞猜", "目标点数"],
                        prompt="只输出格子编号",
                    )
                ],
                state_store="state.json",
            ),
            AIConfig(),
            Path(tmp),
            solver_func=lambda text, images, template: "答案：3",
        )
        message = FakeMessage("🎯 九宫格骰子竞猜（v1.1.4）\n目标点数：25（9 格里唯一）")

        result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert result.metadata["template_id"] == "dice"
    assert message.responses == ["3"]


def test_ai_decrypt_template_requires_all_keywords() -> None:
    module = AIDecryptModule(
        ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
        AIDecryptConfig(
            templates=[
                AIDecryptTemplateConfig(
                    id="qingwa",
                    trigger_keywords=["请识别图片中的口令", "红包ID", "数学题"],
                )
            ]
        ),
        AIConfig(),
        solver_func=lambda text, images, template: "3040 口令",
    )

    result = asyncio.run(module.handle_message(FakeEvent(FakeMessage("红包ID: W4G5CK\n数学题"))))

    assert result.status == "ignored"


def test_ai_decrypt_empty_keyword_template_does_not_match_everything() -> None:
    module = AIDecryptModule(
        ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
        AIDecryptConfig(
            templates=[
                AIDecryptTemplateConfig(
                    id="empty",
                    trigger_keywords=[],
                )
            ]
        ),
        AIConfig(),
        solver_func=lambda text, images, template: "3",
    )

    result = asyncio.run(module.handle_message(FakeEvent(FakeMessage("普通带图聊天"))))

    assert result.status == "ignored"


def test_ai_decrypt_skips_duplicate_puzzle_id_within_ttl() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        module = AIDecryptModule(
            ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
            AIDecryptConfig(
                templates=[
                    AIDecryptTemplateConfig(
                        id="qingwa",
                        trigger_keywords=["请识别图片中的口令", "红包ID", "数学题"],
                        id_markers=["红包ID:"],
                    )
                ],
                state_store="state.json",
            ),
            AIConfig(),
            Path(tmp),
            solver_func=lambda text, images, template: "1140 炼厉書",
        )
        text = "红包ID: W4G5CK\n请识别图片中的口令\n数学题\n1. 24 × 48 = ?"
        first = FakeMessage(text)
        second = FakeMessage(text, message_id=2)

        first_result = asyncio.run(module.handle_message(FakeEvent(first)))
        second_result = asyncio.run(module.handle_message(FakeEvent(second)))

    assert first_result.status == "handled"
    assert second_result.status == "ignored"
    assert first.responses == ["1140 炼厉書"]
    assert second.responses == []



def test_ai_decrypt_concurrent_duplicate_only_replies_once() -> None:
    import tempfile

    async def slow_solver(text, images, template):
        await asyncio.sleep(0.05)
        return "5"

    async def run_case(module: AIDecryptModule, event: FakeEvent):
        return await asyncio.gather(module.handle_message(event), module.handle_message(event))

    with tempfile.TemporaryDirectory() as tmp:
        module = AIDecryptModule(
            ModuleCard("ai_decrypt", "AI decrypt", "", "ai", enabled=True),
            AIDecryptConfig(
                templates=[
                    AIDecryptTemplateConfig(
                        id="puzzle",
                        trigger_keywords=["puzzle"],
                        id_markers=["ID:"],
                        require_media=False,
                        prompt="answer only",
                    )
                ],
                state_store="state.json",
            ),
            AIConfig(),
            Path(tmp),
            solver_func=slow_solver,
        )
        message = FakeMessage("puzzle\nID: X1")
        results = asyncio.run(run_case(module, FakeEvent(message)))

    assert sorted(result.status for result in results) == ["handled", "ignored"]
    assert message.responses == ["5"]

def test_ai_decrypt_sanitizes_answers_and_skips_commands() -> None:
    assert sanitize_answer("答案：  3\n") == "3"
    assert sanitize_answer("最终答案: 1140 炼厉書") == "1140 炼厉書"


def test_ai_decrypt_builtin_24_points_template_handles_text_only(tmp_path: Path) -> None:
    config = AIDecryptConfig(
        templates=[
            AIDecryptTemplateConfig(
                id="twenty-four-points",
                name="24 点算式",
                trigger_keywords=["24 点开始", "数字：", "可用符号"],
                require_media=False,
            )
        ],
        state_store="state.json",
    )
    module = AIDecryptModule(
        ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
        config,
        AIConfig(),
        tmp_path,
        solver_func=lambda text, images, template: "(5-4/5)*5",
    )
    message = FakeMessage(
        "24 点开始\n━━━━━━━━\n数字：[ 5 ] [ 5 ] [ 4 ] [ 5 ]\n奖金：123\n可用符号：+ - x ÷ * / ( )",
        media=False,
    )

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert result.metadata["template_id"] == "twenty-four-points"
    assert message.responses == ["(5-4/5)*5"]


def test_ai_decrypt_24_points_template_ignores_space_differences() -> None:
    module = AIDecryptModule(
        ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
        AIDecryptConfig(
            templates=[
                AIDecryptTemplateConfig(
                    id="twenty-four-points",
                    trigger_keywords=["24 点开始", "数字：", "可用符号"],
                    require_media=False,
                )
            ]
        ),
        AIConfig(),
    )

    template = module.match_template("24点开始\n数字：[ 1 ] [ 2 ] [ 3 ] [ 4 ]\n可用符号：+ - * /")

    assert template is not None
    assert template.id == "twenty-four-points"


def test_ai_decrypt_config_migrates_24_points_template() -> None:
    config = AppConfig.from_dict(
        {
            "ai_decrypt": {
                "templates": [
                    {
                        "id": "dice-grid",
                        "name": "九宫格骰子竞猜",
                        "trigger_keywords": ["九宫格骰子竞猜", "目标点数"],
                    }
                ]
            }
        }
    )

    migrated = {template.id: template for template in config.ai_decrypt.templates}

    assert "twenty-four-points" in migrated
    assert migrated["twenty-four-points"].require_media is False


def test_ai_decrypt_sends_raw_text_and_images_without_template_prompt() -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="3")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.responses = FakeResponses()

        async def close(self):
            captured["closed"] = True

    original_openai = ai_decrypt_module.AsyncOpenAI
    try:
        ai_decrypt_module.AsyncOpenAI = FakeOpenAI
        module = AIDecryptModule(
            ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
            AIDecryptConfig(),
            AIConfig(reply_provider=AIProviderConfig(api_key="key", model="gpt-test")),
            solver_func=None,
        )
        text = "九宫格骰子竞猜\n目标点数：25\n请根据图片规则作答"
        answer = asyncio.run(
            module._call_ai_solver(
                text,
                [{"label": "题目图片", "url": "data:image/png;base64,abc"}],
                AIDecryptTemplateConfig(id="dice", trigger_keywords=["九宫格"], prompt="这个提示词不能被发送"),
            )
        )
    finally:
        ai_decrypt_module.AsyncOpenAI = original_openai

    assert answer == "3"
    assert captured["model"] == "gpt-test"
    input_items = captured["input"]
    assert isinstance(input_items, list)
    assert len(input_items) == 1
    assert input_items[0]["role"] == "user"
    content = input_items[0]["content"]
    assert content == [
        {"type": "input_text", "text": text},
        {"type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "original"},
    ]


def test_ai_decrypt_chat_completions_channel_uses_chat_payload() -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="3"))],
                usage=None,
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self) -> None:
            captured["closed"] = True

    original_openai = ai_decrypt_module.AsyncOpenAI
    try:
        ai_decrypt_module.AsyncOpenAI = FakeOpenAI
        module = AIDecryptModule(
            ModuleCard("ai_decrypt", "AI 解密", "", "ai", enabled=True),
            AIDecryptConfig(max_tokens=64),
            AIConfig(
                reply_provider=AIProviderConfig(
                    provider_type="openai-compatible-chat",
                    base_url="http://sub2api.example/v1",
                    api_key="key",
                    model="gpt-5.6-sol",
                )
            ),
            solver_func=None,
        )
        module._record_ai_usage = lambda *args, **kwargs: None
        answer = asyncio.run(
            module._call_ai_solver(
                "识别题目",
                [{"label": "题目图片", "url": "data:image/png;base64,abc"}],
                AIDecryptTemplateConfig(id="dice", trigger_keywords=["识别"]),
            )
        )
    finally:
        ai_decrypt_module.AsyncOpenAI = original_openai

    request = captured["request"]
    assert isinstance(request, dict)
    assert request["max_tokens"] == 64
    assert "max_output_tokens" not in request
    assert request["messages"][0]["role"] == "user"
    assert request["messages"][0]["content"][-1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,abc", "detail": "auto"},
    }
    assert answer == "3"
    assert captured["closed"] is True


if __name__ == "__main__":
    test_ai_decrypt_dice_template_sends_solver_answer()
    test_ai_decrypt_template_requires_all_keywords()
    test_ai_decrypt_empty_keyword_template_does_not_match_everything()
    test_ai_decrypt_skips_duplicate_puzzle_id_within_ttl()
    test_ai_decrypt_concurrent_duplicate_only_replies_once()
    test_ai_decrypt_sanitizes_answers_and_skips_commands()
    test_ai_decrypt_builtin_24_points_template_handles_text_only()
    test_ai_decrypt_24_points_template_ignores_space_differences()
    test_ai_decrypt_config_migrates_24_points_template()
    test_ai_decrypt_sends_raw_text_and_images_without_template_prompt()
    print("PASS test_ai_decrypt")
