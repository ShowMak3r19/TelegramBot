"""Messages 风格接口的共享适配层。

与 ai_responses.py 平行：当 provider_type 为 claude/anthropic 时，
ai_reply / ai_decrypt / ai_image 通过此层调用 Anthropic Messages API；
当 provider_type 为 openai-chat-completions / openai-compatible-chat 时，
复用这里的 Chat Completions 消息构造与结果解析。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from telegram_bot.shared.telegram_io import obj_get

try:
    from anthropic import Anthropic, AsyncAnthropic
except ImportError:  # pragma: no cover - exercised only in deployments missing deps.
    Anthropic = None  # type: ignore[assignment]
    AsyncAnthropic = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# provider_type 取这些值时走 Anthropic 路径，其余（openai / openai-compatible）保持原 Responses 路径。
ANTHROPIC_PROVIDER_TYPES = {"claude", "anthropic"}
CHAT_COMPLETIONS_PROVIDER_TYPES = {"openai-chat-completions", "openai-compatible-chat"}

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)
_EFFORT_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "minimal": "low",
}


def is_anthropic_provider(provider_type: str | None) -> bool:
    return (provider_type or "").strip().lower() in ANTHROPIC_PROVIDER_TYPES


def is_chat_completions_provider(provider_type: str | None) -> bool:
    return (provider_type or "").strip().lower() in CHAT_COMPLETIONS_PROVIDER_TYPES


def make_async_anthropic_client(api_key: str, base_url: str, timeout: float) -> Any:
    if AsyncAnthropic is None:
        raise RuntimeError("缺少 anthropic 依赖，请重新安装 requirements.txt。")
    return AsyncAnthropic(**_client_kwargs(api_key, base_url, timeout))


def make_sync_anthropic_client(api_key: str, base_url: str, timeout: float) -> Any:
    if Anthropic is None:
        raise RuntimeError("缺少 anthropic 依赖，请重新安装 requirements.txt。")
    return Anthropic(**_client_kwargs(api_key, base_url, timeout))


def _client_kwargs(api_key: str, base_url: str, timeout: float) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
    cleaned = (base_url or "").strip().rstrip("/")
    if cleaned:
        # 留空时使用 SDK 默认 https://api.anthropic.com；填写则视为自建/代理网关。
        kwargs["base_url"] = cleaned
    return kwargs


def map_anthropic_effort(reasoning_effort: str | None) -> str | None:
    return _EFFORT_MAP.get((reasoning_effort or "").strip().lower())


def anthropic_image_block(image_url: str) -> dict[str, Any] | None:
    """把 collect_image_inputs_for_responses 产出的图片 URL 转为 Anthropic image content 块。"""
    url = (image_url or "").strip()
    if not url:
        return None
    match = _DATA_URL_RE.match(url)
    if match:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": match.group("mime"),
                "data": match.group("data"),
            },
        }
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def build_openai_chat_messages(
    user_text: str,
    image_inputs: list[dict[str, str]],
    image_detail: str,
    *,
    developer_prompt: str = "",
    system_prompt: str = "",
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_parts = [part.strip() for part in (developer_prompt, system_prompt) if part and part.strip()]
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for index, image_input in enumerate(image_inputs, start=1):
        image_block = openai_chat_image_block(image_input.get("url", ""), image_detail)
        if image_block is None:
            continue
        label = image_input.get("label") or f"图{index}"
        user_content.append({"type": "text", "text": f"{label}如下。用户如果提到图{index}，请按这个顺序对应。"})
        user_content.append(image_block)
    messages.append({"role": "user", "content": user_content})
    return messages


def openai_chat_image_block(image_url: str, image_detail: str) -> dict[str, Any] | None:
    url = (image_url or "").strip()
    if not url:
        return None
    payload: dict[str, Any] = {"url": url}
    normalized_detail = normalize_openai_chat_image_detail(image_detail)
    if normalized_detail:
        payload["detail"] = normalized_detail
    return {"type": "image_url", "image_url": payload}


def normalize_openai_chat_image_detail(image_detail: str | None) -> str | None:
    normalized = (image_detail or "").strip().lower()
    return {
        "auto": "auto",
        "low": "low",
        "high": "high",
        "original": "auto",
    }.get(normalized)


async def anthropic_create_message(client: Any, request_kwargs: dict[str, Any]) -> Any:
    """异步流式调用 Messages API 并返回完整消息。

    用流式 + get_final_message 规避大 max_tokens 的非流式超时保护；
    若 SDK 版本不认识 thinking/output_config 等较新参数（TypeError），剥离后重试基础能力。
    """
    try:
        async with client.messages.stream(**request_kwargs) as stream:
            return await stream.get_final_message()
    except TypeError:
        reduced = _strip_advanced_kwargs(request_kwargs)
        if reduced == request_kwargs:
            raise
        logger.warning("Anthropic SDK 不支持高级参数，已剥离 thinking/output_config 后重试。")
        async with client.messages.stream(**reduced) as stream:
            return await stream.get_final_message()


def _strip_advanced_kwargs(request_kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request_kwargs.items() if key not in ("thinking", "output_config")}


async def aclose_anthropic(client: Any) -> None:
    """兼容不同 SDK 版本的关闭方法，吞掉关闭异常。"""
    for name in ("close", "aclose"):
        fn = getattr(client, name, None)
        if fn is None:
            continue
        try:
            result = fn()
            if hasattr(result, "__await__"):
                await result
            return
        except Exception:  # pragma: no cover - 关闭失败无需影响主流程
            continue


def collect_anthropic_text_and_sources(message: Any) -> tuple[str, list[tuple[str, str]]]:
    text_parts: list[str] = []
    sources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for block in obj_get(message, "content", []) or []:
        block_type = obj_get(block, "type")
        if block_type == "text":
            txt = obj_get(block, "text")
            if txt:
                text_parts.append(str(txt))
            for citation in obj_get(block, "citations", []) or []:
                _append_source(citation, sources, seen_urls)
        elif block_type == "web_search_tool_result":
            for item in obj_get(block, "content", []) or []:
                _append_source(item, sources, seen_urls)
    return "".join(text_parts).strip(), sources


def collect_chat_completions_text_and_sources(response: Any) -> tuple[str, list[tuple[str, str]]]:
    text_parts: list[str] = []
    sources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for choice in obj_get(response, "choices", []) or []:
        message = obj_get(choice, "message", {}) or {}
        content = obj_get(message, "content")
        text = _chat_content_text(content, sources, seen_urls)
        if not text:
            text = _chat_content_text(obj_get(choice, "delta"), sources, seen_urls)
        if not text:
            text = str(obj_get(message, "refusal", "") or "").strip()
        if text:
            text_parts.append(text)
    answer = "\n".join(part for part in text_parts if part).strip()
    if not answer:
        answer = str(obj_get(response, "output_text", "") or "").strip()
    return answer, sources


def collect_chat_completions_reasoning(response: Any) -> str:
    parts: list[str] = []
    for choice in obj_get(response, "choices", []) or []:
        _append_reasoning_parts(parts, obj_get(choice, "reasoning"))
        _append_reasoning_parts(parts, obj_get(obj_get(choice, "message", {}) or {}, "reasoning"))
    return "\n\n".join(part for part in parts if part).strip()


def _append_source(item: Any, sources: list[tuple[str, str]], seen_urls: set[str]) -> None:
    url = obj_get(item, "url")
    if not url or url in seen_urls:
        return
    title = obj_get(item, "title") or obj_get(item, "cited_text") or url
    seen_urls.add(str(url))
    sources.append((str(title), str(url)))


def _chat_content_text(content: Any, sources: list[tuple[str, str]], seen_urls: set[str]) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = obj_get(content, "text", obj_get(content, "content", "")) or ""
        for annotation in obj_get(content, "annotations", []) or []:
            _append_source(annotation, sources, seen_urls)
        return str(text).strip()
    parts: list[str] = []
    for item in content or []:
        item_type = obj_get(item, "type")
        if item_type in {"text", "output_text"}:
            text = obj_get(item, "text", obj_get(item, "content", ""))
            if text:
                parts.append(str(text).strip())
            for annotation in obj_get(item, "annotations", []) or []:
                _append_source(annotation, sources, seen_urls)
        elif item_type == "refusal":
            refusal = obj_get(item, "refusal", obj_get(item, "text", ""))
            if refusal:
                parts.append(str(refusal).strip())
    return "\n".join(part for part in parts if part).strip()


def _append_reasoning_parts(parts: list[str], value: Any) -> None:
    if not value:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            parts.append(text)
        return
    if isinstance(value, dict):
        for key in ("text", "content", "summary"):
            nested = obj_get(value, key)
            if isinstance(nested, str) and nested.strip():
                parts.append(nested.strip())
            elif isinstance(nested, list):
                for item in nested:
                    _append_reasoning_parts(parts, item)
        return
    if isinstance(value, list):
        for item in value:
            _append_reasoning_parts(parts, item)


def collect_anthropic_thinking(message: Any) -> str:
    parts: list[str] = []
    for block in obj_get(message, "content", []) or []:
        if obj_get(block, "type") != "thinking":
            continue
        thinking = obj_get(block, "thinking")
        if thinking:
            parts.append(str(thinking).strip())
    return "\n\n".join(part for part in parts if part).strip()
