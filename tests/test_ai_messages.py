from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.shared.ai_messages import (
    anthropic_image_block,
    build_openai_chat_messages,
    collect_anthropic_text_and_sources,
    collect_anthropic_thinking,
    collect_chat_completions_reasoning,
    collect_chat_completions_text_and_sources,
    is_anthropic_provider,
    is_chat_completions_provider,
    map_anthropic_effort,
)
from telegram_bot.shared.ai_responses import build_token_stats


def test_is_anthropic_provider() -> None:
    assert is_anthropic_provider("claude") is True
    assert is_anthropic_provider("Anthropic") is True
    assert is_anthropic_provider("  CLAUDE ") is True
    assert is_anthropic_provider("openai") is False
    assert is_anthropic_provider("openai-compatible") is False
    assert is_anthropic_provider("") is False
    assert is_anthropic_provider(None) is False


def test_is_chat_completions_provider() -> None:
    assert is_chat_completions_provider("openai-compatible-chat") is True
    assert is_chat_completions_provider("  OPENAI-COMPATIBLE-CHAT ") is True
    assert is_chat_completions_provider("openai") is False
    assert is_chat_completions_provider("openai-compatible") is False
    assert is_chat_completions_provider("claude") is False
    assert is_chat_completions_provider(None) is False


def test_openai_chat_messages_convert_prompts_and_images() -> None:
    messages = build_openai_chat_messages(
        "分析图片",
        [{"label": "引用图1", "url": "data:image/png;base64,AAAB"}],
        "original",
        developer_prompt="开发者要求",
        system_prompt="系统要求",
    )

    assert messages[0] == {"role": "system", "content": "开发者要求\n\n系统要求"}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == [
        {"type": "text", "text": "分析图片"},
        {"type": "text", "text": "引用图1如下。用户如果提到图1，请按这个顺序对应。"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAAB", "detail": "auto"},
        },
    ]


def test_collect_chat_completions_response_text_reasoning_and_usage() -> None:
    response = {
        "choices": [
            {
                "message": {"content": "答案", "reasoning": "简要推理"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    assert collect_chat_completions_text_and_sources(response) == ("答案", [])
    assert collect_chat_completions_reasoning(response) == "简要推理"
    assert "Total: 15" in build_token_stats(response)


def test_anthropic_image_block_data_url() -> None:
    block = anthropic_image_block("data:image/png;base64,AAAB")
    assert block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAB"},
    }


def test_anthropic_image_block_http_url() -> None:
    block = anthropic_image_block("https://example.com/a.jpg")
    assert block == {"type": "image", "source": {"type": "url", "url": "https://example.com/a.jpg"}}


def test_anthropic_image_block_invalid() -> None:
    assert anthropic_image_block("") is None
    assert anthropic_image_block("not-a-url") is None


def test_map_anthropic_effort() -> None:
    assert map_anthropic_effort("high") == "high"
    assert map_anthropic_effort("minimal") == "low"
    assert map_anthropic_effort("none") is None
    assert map_anthropic_effort(None) is None


def _fake_message() -> dict:
    return {
        "content": [
            {"type": "thinking", "thinking": "推理过程"},
            {"type": "server_tool_use", "name": "web_search"},
            {
                "type": "web_search_tool_result",
                "content": [
                    {"type": "web_search_result", "url": "https://a.com", "title": "A"},
                    {"type": "web_search_result", "url": "https://a.com", "title": "重复应去重"},
                ],
            },
            {"type": "text", "text": "答案是 42。", "citations": [{"url": "https://b.com", "title": "B"}]},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "end_turn",
    }


def test_collect_anthropic_text_and_sources() -> None:
    text, sources = collect_anthropic_text_and_sources(_fake_message())
    assert text == "答案是 42。"
    assert ("A", "https://a.com") in sources
    assert ("B", "https://b.com") in sources
    assert len(sources) == 2  # 同一 url 去重


def test_collect_anthropic_thinking() -> None:
    assert collect_anthropic_thinking(_fake_message()) == "推理过程"


def test_token_stats_helper_reused_for_anthropic_usage() -> None:
    # 复用 ai_responses 的 token 统计：Anthropic 的 input_tokens/output_tokens 也能被解析。
    stats = build_token_stats(_fake_message())
    assert "In: 10" in stats
    assert "Out: 5" in stats
    assert "Total: 15" in stats
