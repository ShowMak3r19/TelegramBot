from __future__ import annotations

import html
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import AIConfig, AIReplyConfig
from telegram_bot.shared import telegram_media
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.ai_responses import (
    build_sources_html,
    build_token_stats,
    collect_image_inputs_for_responses,
    collect_reasoning_summary,
    collect_response_text_and_sources,
    extract_requested_image_indexes,
    extract_usage_counts,
)
from telegram_bot.shared.ai_messages import (
    aclose_anthropic,
    anthropic_create_message,
    anthropic_image_block,
    build_openai_chat_messages,
    collect_anthropic_text_and_sources,
    collect_anthropic_thinking,
    collect_chat_completions_reasoning,
    collect_chat_completions_text_and_sources,
    is_anthropic_provider,
    is_chat_completions_provider,
    make_async_anthropic_client,
    map_anthropic_effort,
)
from telegram_bot.shared.telegram_io import (
    TELEGRAM_SAFE_TEXT_LIMIT,
    event_message as _event_message,
    get_reply_message as _get_reply_message,
    is_outgoing as _is_outgoing,
    message_text as _message_text,
    obj_get,
    safe_delete_message,
    safe_edit_message,
    truncate_text,
)
from telegram_bot.shared.telegram_media import media_size_bytes, representative_frame_positions

from .base import ModuleCard

logger = logging.getLogger(__name__)

MAX_CONTEXT_TEXT_CHARS = 8000

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - exercised only in deployments missing deps.
    AsyncOpenAI = None  # type: ignore[assignment]


class AIReplyModule:
    def __init__(self, card: ModuleCard, config: AIConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.usage_path = self._resolve_path("runtime/data/ai_usage.jsonl")
        self.settings_path = self._resolve_path(self.config.reply.settings_store)
        self._load_ai_settings()
        self._sync_card_config()

    async def start(self) -> None:
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not self.config.reply_provider.enabled:
            return HandlerResult.ignored(self.card.id)
        if not _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        if await self._handle_message_info_command(event):
            return HandlerResult.handled(self.card.id, "message info sent")

        if await self._handle_ai_setting_command(event):
            return HandlerResult.handled(self.card.id, "ai setting updated")

        message = _event_message(event)
        text = _message_text(message or event)
        prompt = extract_ai_prompt(text, bool(getattr(message, "is_reply", False)), self.config.reply)
        if prompt is None:
            return HandlerResult.ignored(self.card.id)

        try:
            await self._handle_ai_chat(event, prompt)
        except Exception as exc:
            logger.exception("AI auto reply failed: %s", exc)
            return HandlerResult.failed(self.card.id, str(exc))
        return HandlerResult.handled(self.card.id, "ai reply sent", {"prompt": prompt})

    def update_config(self, values: dict[str, Any]) -> None:
        reply_values = values.get("reply")
        if isinstance(reply_values, dict):
            self.config.reply = _reply_config_from_dict({**asdict(self.config.reply), **reply_values})
        provider_values = values.get("reply_provider")
        if isinstance(provider_values, dict):
            for key in ("name", "provider_type", "base_url", "model"):
                if key in provider_values:
                    setattr(self.config.reply_provider, key, str(provider_values.get(key) or ""))
            if "enabled" in provider_values:
                self.config.reply_provider.enabled = bool(provider_values["enabled"])
            if str(provider_values.get("api_key") or "").strip():
                self.config.reply_provider.api_key = str(provider_values["api_key"]).strip()
        self.settings_path = self._resolve_path(self.config.reply.settings_store)
        self._sync_card_config()

    async def _handle_ai_chat(self, event: Any, prompt: str) -> None:
        message = _event_message(event)
        if message is None:
            return

        provider_type = self.config.reply_provider.provider_type
        use_anthropic = is_anthropic_provider(provider_type)
        use_chat_completions = is_chat_completions_provider(provider_type)
        service_label = (
            "Anthropic Messages"
            if use_anthropic
            else "OpenAI Chat Completions"
            if use_chat_completions
            else "OpenAI Responses"
        )
        replied_message = await _get_reply_message(message)
        reply_text = _message_text(replied_message) if replied_message is not None else ""
        reply_has_media = bool(replied_message and getattr(replied_message, "media", None))
        quoted_for_display = "" if reply_has_media else reply_text
        if reply_text and prompt:
            question_for_display = prompt
            current_request = f"我回复了一条消息。被回复的消息如下：\n{reply_text}\n\n我的问题：\n{prompt}"
        elif reply_text:
            question_for_display = "请回答这条引用消息"
            current_request = f"请回答我回复的这条消息：\n{reply_text}"
        else:
            question_for_display = prompt or "继续根据上下文回答"
            current_request = prompt or "请根据最近上下文继续回答。"

        rendered_message = message
        initial_text = format_ai_group_message(
            question_for_display,
            "正在思考中……",
            self.config.reply_provider.model,
            quoted_for_display,
            service_label=service_label,
        )

        async def render_placeholder() -> None:
            nonlocal rendered_message
            deleted = await safe_delete_message(message, "ai_reply_trigger")
            if not deleted or not hasattr(event, "client"):
                await safe_edit_message(message, initial_text, parse_mode="html", link_preview=False)
                return
            send_kwargs: dict[str, Any] = {
                "parse_mode": "html",
                "link_preview": False,
            }
            if reply_has_media and replied_message is not None and getattr(replied_message, "id", None) is not None:
                send_kwargs["reply_to"] = getattr(replied_message, "id")
            rendered_message = await event.client.send_message(
                getattr(message, "chat_id", getattr(event, "chat_id", None)),
                initial_text,
                **send_kwargs,
            )

        image_inputs: list[dict[str, str]]
        media_error: str | None
        if getattr(message, "media", None):
            image_inputs, media_error = await collect_image_inputs_for_responses(event, prompt)
            await render_placeholder()
        else:
            await render_placeholder()
            image_inputs, media_error = await collect_image_inputs_for_responses(event, prompt)
        if media_error:
            logger.warning("AI media input hint: %s", media_error)

        context_text = await collect_context_with_reply_text(event, self.config.reply, reply_text)
        user_content_parts: list[str] = []
        if context_text:
            user_content_parts.append(context_text[:MAX_CONTEXT_TEXT_CHARS])
        user_content_parts.append("本次用户要求：\n" + current_request)
        user_content = "\n\n".join(user_content_parts)

        logger.info(
            "Triggering AI chat service=%s prompt=%s images=%s",
            service_label,
            (prompt or "[reply]")[:120],
            len(image_inputs),
        )
        started_at = time.monotonic()

        try:
            if use_anthropic:
                answer_html, reasoning_html, powered_by, token_stats = await self._call_anthropic_messages_api(user_content, image_inputs)
            elif use_chat_completions:
                answer_html, reasoning_html, powered_by, token_stats = await self._call_openai_chat_completions_api(
                    user_content,
                    image_inputs,
                )
            else:
                answer_html, reasoning_html, powered_by, token_stats = await self._call_openai_responses_api(user_content, image_inputs)
            elapsed_seconds = time.monotonic() - started_at
            final_text = format_ai_group_message(
                question_for_display,
                answer_html,
                self.config.reply_provider.model,
                quoted_for_display,
                answer_is_html=True,
                powered_by=powered_by,
                token_stats=token_stats,
                elapsed_seconds=elapsed_seconds,
                reasoning_html=reasoning_html,
                service_label=service_label,
            )
        except Exception as exc:
            logger.exception("AI chat failed (%s): %s", service_label, exc)
            elapsed_seconds = time.monotonic() - started_at
            error_html = format_markdown_for_telegram(f"{service_label} API 出错：{exc}")
            final_text = format_ai_group_message(
                question_for_display,
                error_html,
                self.config.reply_provider.model,
                quoted_for_display,
                answer_is_html=True,
                powered_by=f"{service_label} × {self.config.reply_provider.model}",
                elapsed_seconds=elapsed_seconds,
                service_label=service_label,
            )
        await safe_edit_message(rendered_message, final_text, parse_mode="html", link_preview=False)

    async def _handle_message_info_command(self, event: Any) -> bool:
        reply = self.config.reply
        if not reply.message_info_enabled:
            return False

        message = _event_message(event)
        text = _message_text(message or event).strip()
        if not command_matches_prefix(text, reply.message_info_command_prefixes):
            return False

        deleted = await safe_delete_message(message, "message_info_trigger")
        if not getattr(message, "is_reply", False):
            if deleted and hasattr(event, "client"):
                await event.client.send_message(
                    getattr(message, "chat_id", getattr(event, "chat_id", None)),
                    format_message_info_hint(reply),
                    parse_mode="html",
                )
            else:
                await safe_edit_message(message, format_message_info_hint(reply), parse_mode="html")
            return True

        replied = await _get_reply_message(message)
        if replied is None and deleted and hasattr(event, "client"):
            await event.client.send_message(
                getattr(message, "chat_id", getattr(event, "chat_id", None)),
                "未能读取被引用消息。",
                parse_mode="html",
            )
            return True
        if replied is None:
            await safe_edit_message(message, "未能读取被引用消息。", parse_mode="html")
            return True

        payload = await build_message_info_payload(event, replied)
        rendered = format_message_info_block(payload)
        if deleted and hasattr(event, "client"):
            await event.client.send_message(
                getattr(message, "chat_id", getattr(event, "chat_id", None)),
                rendered,
                parse_mode="html",
                link_preview=False,
                reply_to=getattr(replied, "id", None),
            )
        else:
            await safe_edit_message(message, rendered, parse_mode="html", link_preview=False)
        return True

    async def _call_openai_responses_api(self, effective_prompt: str, image_inputs: list[dict[str, str]]) -> tuple[str, str, str, str]:
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt。")
        provider = self.config.reply_provider
        reply = self.config.reply
        if not provider.api_key:
            raise ValueError("AI 功能未配置 api_key，请在管理后台或 config.json 的 ai.reply_provider.api_key 中配置。")
        if not provider.model:
            raise ValueError("AI 功能未配置 model，请在管理后台或 config.json 中配置。")

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url.rstrip("/"), timeout=reply.timeout_seconds)
        input_items: list[dict[str, Any]] = []
        developer_prompt = build_developer_prompt(reply)
        if developer_prompt:
            input_items.append({"role": "developer", "content": developer_prompt})
        if reply.system_prompt.strip():
            input_items.append({"role": "system", "content": reply.system_prompt.strip()})

        user_content: list[dict[str, Any]] = [{"type": "input_text", "text": effective_prompt}]
        for index, image_input in enumerate(image_inputs, start=1):
            image_url = image_input.get("url", "")
            label = image_input.get("label") or f"图{index}"
            if not image_url:
                continue
            user_content.append({"type": "input_text", "text": f"{label}如下。用户如果提到图{index}，请按这个顺序对应。"})
            user_content.append({"type": "input_image", "image_url": image_url, "detail": reply.image_detail})
        input_items.append({"role": "user", "content": user_content})

        request_kwargs: dict[str, Any] = {
            "model": provider.model,
            "input": input_items,
            "store": False,
            "max_output_tokens": reply.max_tokens,
        }
        if supports_responses_controls(provider.model):
            if reply.reasoning_effort != "none":
                reasoning_payload: dict[str, Any] = {"effort": reply.reasoning_effort}
                if reply.reasoning_summary:
                    reasoning_payload["summary"] = "auto"
                request_kwargs["reasoning"] = reasoning_payload
            request_kwargs["text"] = {"verbosity": reply.text_verbosity}
        else:
            # 推理模型（gpt-5/o3/o4）不支持 temperature，仅对其他模型下发
            request_kwargs["temperature"] = reply.temperature
        if reply.web_search:
            request_kwargs["tools"] = [{"type": "web_search"}]
            request_kwargs["include"] = ["web_search_call.action.sources"]

        logger.info(
            "AI Responses request started model=%s base_url=%s images=%s web_search=%s reasoning=%s max_output_tokens=%s",
            provider.model,
            provider.base_url.rstrip("/"),
            len(image_inputs),
            reply.web_search,
            reply.reasoning_effort,
            reply.max_tokens,
        )
        started_at = time.monotonic()
        try:
            response = await client.responses.create(**request_kwargs)
            self._record_ai_usage("ai_chat", "responses", provider.model, True, started_at, response)
        except Exception as exc:
            self._record_ai_usage("ai_chat", "responses", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            try:
                await client.close()
            except Exception:
                pass

        status = str(obj_get(response, "status", "") or "").strip().lower()
        incomplete_details = obj_get(response, "incomplete_details", {}) or {}
        incomplete_reason = str(obj_get(incomplete_details, "reason", "") or "").strip().lower()
        answer, sources = collect_response_text_and_sources(response)
        reasoning_summary = collect_reasoning_summary(response)
        token_stats = build_token_stats(response)
        if status == "incomplete" and incomplete_reason:
            answer = (answer or "（模型未返回可显示文本）") + f"\n\n[输出未完成：{incomplete_reason}]"
        final_html = format_markdown_for_telegram(answer or "（模型未返回可显示文本）")
        sources_html = build_sources_html(sources)
        if sources_html:
            final_html = f"{final_html}\n\n{sources_html}"
        reasoning_html = format_markdown_for_telegram(reasoning_summary) if reasoning_summary else ""
        powered_by = "Responses API"
        if sources_html:
            powered_by += " + web_search"
        if image_inputs:
            powered_by += f" + Vision×{len(image_inputs)}" if len(image_inputs) > 1 else " + Vision"
        if reasoning_summary:
            powered_by += " + reasoning_summary"
        powered_by += f" × {provider.model}"
        return final_html, reasoning_html, powered_by, token_stats

    async def _call_openai_chat_completions_api(
        self,
        effective_prompt: str,
        image_inputs: list[dict[str, str]],
    ) -> tuple[str, str, str, str]:
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt。")
        provider = self.config.reply_provider
        reply = self.config.reply
        if not provider.api_key:
            raise ValueError("AI 功能未配置 api_key，请在管理后台或 config.json 的 ai.reply_provider.api_key 中配置。")
        if not provider.model:
            raise ValueError("AI 功能未配置 model，请在管理后台或 config.json 中配置。")

        client_kwargs: dict[str, Any] = {"api_key": provider.api_key, "timeout": reply.timeout_seconds}
        if provider.base_url.strip():
            client_kwargs["base_url"] = provider.base_url.rstrip("/")
        client = AsyncOpenAI(**client_kwargs)
        request_kwargs: dict[str, Any] = {
            "model": provider.model,
            "messages": build_openai_chat_messages(
                effective_prompt,
                image_inputs,
                reply.image_detail,
                developer_prompt=build_developer_prompt(reply),
                system_prompt=reply.system_prompt.strip(),
            ),
            "max_tokens": reply.max_tokens,
        }
        if supports_responses_controls(provider.model):
            if reply.reasoning_effort != "none":
                request_kwargs["reasoning_effort"] = reply.reasoning_effort
        else:
            request_kwargs["temperature"] = reply.temperature

        logger.info(
            "AI Chat Completions request started model=%s base_url=%s images=%s reasoning=%s max_tokens=%s",
            provider.model,
            (provider.base_url or "").rstrip("/"),
            len(image_inputs),
            reply.reasoning_effort,
            reply.max_tokens,
        )
        started_at = time.monotonic()
        try:
            response = await client.chat.completions.create(**request_kwargs)
            self._record_ai_usage("ai_chat", "chat_completions", provider.model, True, started_at, response)
        except Exception as exc:
            self._record_ai_usage("ai_chat", "chat_completions", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            try:
                await client.close()
            except Exception:
                pass

        answer, sources = collect_chat_completions_text_and_sources(response)
        reasoning_summary = collect_chat_completions_reasoning(response)
        token_stats = build_token_stats(response)
        choices = obj_get(response, "choices", []) or []
        finish_reason = str(obj_get(choices[0] if choices else {}, "finish_reason", "") or "").strip().lower()
        if finish_reason in {"length", "max_tokens"}:
            answer = (answer or "（模型未返回可显示文本）") + "\n\n[输出未完成：max_tokens]"
        final_html = format_markdown_for_telegram(answer or "（模型未返回可显示文本）")
        sources_html = build_sources_html(sources)
        if sources_html:
            final_html = f"{final_html}\n\n{sources_html}"
        reasoning_html = format_markdown_for_telegram(reasoning_summary) if reasoning_summary else ""
        powered_by = "Chat Completions API"
        if sources_html:
            powered_by += " + sources"
        if image_inputs:
            powered_by += f" + Vision×{len(image_inputs)}" if len(image_inputs) > 1 else " + Vision"
        if reasoning_summary:
            powered_by += " + reasoning"
        powered_by += f" × {provider.model}"
        return final_html, reasoning_html, powered_by, token_stats

    async def _call_anthropic_messages_api(self, effective_prompt: str, image_inputs: list[dict[str, str]]) -> tuple[str, str, str, str]:
        provider = self.config.reply_provider
        reply = self.config.reply
        if not provider.api_key:
            raise ValueError("AI 功能未配置 api_key，请在管理后台或 config.json 的 ai.reply_provider.api_key 中配置。")
        if not provider.model:
            raise ValueError("AI 功能未配置 model，请在管理后台或 config.json 中配置。")

        client = make_async_anthropic_client(provider.api_key, provider.base_url, reply.timeout_seconds)
        system_parts: list[str] = []
        developer_prompt = build_developer_prompt(reply)
        if developer_prompt:
            system_parts.append(developer_prompt)
        if reply.system_prompt.strip():
            system_parts.append(reply.system_prompt.strip())

        user_content: list[dict[str, Any]] = [{"type": "text", "text": effective_prompt}]
        for index, image_input in enumerate(image_inputs, start=1):
            image_block = anthropic_image_block(image_input.get("url", ""))
            if image_block is None:
                continue
            label = image_input.get("label") or f"图{index}"
            user_content.append({"type": "text", "text": f"{label}如下。用户如果提到图{index}，请按这个顺序对应。"})
            user_content.append(image_block)

        request_kwargs: dict[str, Any] = {
            "model": provider.model,
            "max_tokens": reply.max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        system_text = "\n\n".join(system_parts)
        if system_text:
            request_kwargs["system"] = system_text
        if reply.web_search:
            request_kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]
        if reply.reasoning_effort and reply.reasoning_effort.lower() != "none":
            thinking_payload: dict[str, Any] = {"type": "adaptive"}
            if reply.reasoning_summary:
                thinking_payload["display"] = "summarized"
            request_kwargs["thinking"] = thinking_payload
            effort = map_anthropic_effort(reply.reasoning_effort)
            if effort:
                request_kwargs["output_config"] = {"effort": effort}

        logger.info(
            "AI Messages request started model=%s base_url=%s images=%s web_search=%s reasoning=%s max_tokens=%s",
            provider.model,
            (provider.base_url or "").rstrip("/"),
            len(image_inputs),
            reply.web_search,
            reply.reasoning_effort,
            reply.max_tokens,
        )
        started_at = time.monotonic()
        try:
            message = await anthropic_create_message(client, request_kwargs)
            self._record_ai_usage("ai_chat", "messages", provider.model, True, started_at, message)
        except Exception as exc:
            self._record_ai_usage("ai_chat", "messages", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            await aclose_anthropic(client)

        answer, sources = collect_anthropic_text_and_sources(message)
        reasoning_summary = collect_anthropic_thinking(message)
        token_stats = build_token_stats(message)
        if obj_get(message, "stop_reason") == "max_tokens":
            answer = (answer or "（模型未返回可显示文本）") + "\n\n[输出未完成：max_tokens]"
        final_html = format_markdown_for_telegram(answer or "（模型未返回可显示文本）")
        sources_html = build_sources_html(sources)
        if sources_html:
            final_html = f"{final_html}\n\n{sources_html}"
        reasoning_html = format_markdown_for_telegram(reasoning_summary) if reasoning_summary else ""
        powered_by = "Messages API"
        if sources_html:
            powered_by += " + web_search"
        if image_inputs:
            powered_by += f" + Vision×{len(image_inputs)}" if len(image_inputs) > 1 else " + Vision"
        if reasoning_summary:
            powered_by += " + thinking"
        powered_by += f" × {provider.model}"
        return final_html, reasoning_html, powered_by, token_stats

    async def _handle_ai_setting_command(self, event: Any) -> bool:
        message = _event_message(event)
        owner_ids = self.config.reply.owner_user_ids
        if owner_ids and getattr(message, "sender_id", None) not in owner_ids:
            return False
        text = _message_text(message or event).strip()
        if not text:
            return False
        first_word, _, value = text.partition(" ")
        shortcuts = {
            "/model": "/ai_model",
            "/m": "/ai_model",
            "/chat_model": "/ai_model",
        }
        command = shortcuts.get(first_word, first_word)
        if not command.startswith("/ai_"):
            return False

        reply = self.config.reply
        if command == "/ai_show":
            await safe_edit_message(
                message,
                (
                    f"<b>AI 设置</b>\n"
                    f"对话模型: <code>{html.escape(self.config.reply_provider.model)}</code>\n"
                    f"reasoning_effort: <code>{html.escape(reply.reasoning_effort)}</code>\n"
                    f"reasoning_summary: <code>{reply.reasoning_summary}</code>\n"
                    f"text_verbosity: <code>{html.escape(reply.text_verbosity)}</code>\n"
                    f"web_search: <code>{reply.web_search}</code>\n"
                    f"image_detail: <code>{html.escape(reply.image_detail)}</code>\n"
                    f"max_tokens: <code>{reply.max_tokens}</code>\n"
                    f"timeout_seconds: <code>{reply.timeout_seconds}</code>"
                ),
                parse_mode="html",
            )
            return True

        if command == "/ai_model" and value.strip():
            self.config.reply_provider.model = value.strip()
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("对话模型", self.config.reply_provider.model), parse_mode="html")
            return True

        if command == "/ai_reasoning" and value.strip():
            normalized = value.strip().lower()
            if normalized not in {"none", "low", "medium", "high", "xhigh"}:
                await safe_edit_message(message, "reasoning_effort 只能是 none|low|medium|high|xhigh")
                return True
            reply.reasoning_effort = normalized
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("reasoning_effort", reply.reasoning_effort), parse_mode="html")
            return True

        if command == "/ai_verbosity" and value.strip():
            normalized = value.strip().lower()
            if normalized not in {"low", "medium", "high"}:
                await safe_edit_message(message, "text_verbosity 只能是 low|medium|high")
                return True
            reply.text_verbosity = normalized
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("text_verbosity", reply.text_verbosity), parse_mode="html")
            return True

        if command in {"/ai_web", "/ai_summary"} and value.strip():
            parsed = parse_bool(value)
            if parsed is None:
                await safe_edit_message(message, "只能设置为 on/off、true/false 或 1/0")
                return True
            if command == "/ai_web":
                reply.web_search = parsed
                setting_name = "web_search"
                setting_value: Any = reply.web_search
            else:
                reply.reasoning_summary = parsed
                setting_name = "reasoning_summary"
                setting_value = reply.reasoning_summary
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message(setting_name, setting_value), parse_mode="html")
            return True

        if command == "/ai_detail" and value.strip():
            normalized = value.strip().lower()
            if normalized not in {"low", "high", "auto", "original"}:
                await safe_edit_message(message, "image_detail 只能是 low|high|auto|original")
                return True
            reply.image_detail = normalized
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("image_detail", reply.image_detail), parse_mode="html")
            return True

        if command == "/ai_tokens" and value.strip():
            try:
                reply.max_tokens = max(256, min(int(value.strip()), 128000))
            except ValueError:
                await safe_edit_message(message, "max_tokens 必须是数字")
                return True
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("max_tokens", reply.max_tokens), parse_mode="html")
            return True

        if command == "/ai_timeout" and value.strip():
            try:
                reply.timeout_seconds = max(5, float(value.strip()))
            except ValueError:
                await safe_edit_message(message, "timeout_seconds 必须是数字")
                return True
            self._save_ai_settings()
            await safe_edit_message(message, format_ai_setting_message("timeout_seconds", reply.timeout_seconds), parse_mode="html")
            return True

        await safe_edit_message(
            message,
            (
                "<b>AI 设置命令</b>\n"
                "<code>/ai_show</code>\n"
                "<code>/model gpt-5.5</code> 或 <code>/ai_model gpt-5.5</code>\n"
                "<code>/ai_reasoning none|low|medium|high|xhigh</code>\n"
                "<code>/ai_verbosity low|medium|high</code>\n"
                "<code>/ai_web on|off</code>\n"
                "<code>/ai_summary on|off</code>\n"
                "<code>/ai_detail low|high|auto|original</code>\n"
                "<code>/ai_tokens 25000</code>\n"
                "<code>/ai_timeout 180</code>"
            ),
            parse_mode="html",
        )
        return True

    def _record_ai_usage(
        self,
        feature: str,
        provider: str,
        model: str,
        success: bool,
        started_at: float,
        source: Any = None,
        error: str = "",
    ) -> None:
        now = time.time()
        record = {
            "ts": now,
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
            "day": time.strftime("%Y-%m-%d", time.localtime(now)),
            "feature": feature or "unknown",
            "provider": provider or "unknown",
            "model": model or "unknown",
            "success": bool(success),
            "latency_ms": int(max(0, (time.monotonic() - started_at) * 1000)),
            **extract_usage_counts(source),
        }
        if error:
            record["error"] = error[:800]
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            logger.exception("Failed to write AI usage stats")

    def _load_ai_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load AI settings store: %s", self.settings_path)
            return
        if data.get("model"):
            self.config.reply_provider.model = str(data["model"])
        reply = self.config.reply
        if data.get("reasoning_effort"):
            reply.reasoning_effort = str(data["reasoning_effort"])
        if data.get("text_verbosity"):
            reply.text_verbosity = str(data["text_verbosity"])
        if data.get("image_detail"):
            reply.image_detail = str(data["image_detail"])
        if "web_search" in data:
            reply.web_search = bool(data["web_search"])
        if "reasoning_summary" in data:
            reply.reasoning_summary = bool(data["reasoning_summary"])
        if "message_info_enabled" in data:
            reply.message_info_enabled = bool(data["message_info_enabled"])
        if isinstance(data.get("message_info_command_prefixes"), list):
            reply.message_info_command_prefixes = [str(item).strip() for item in data["message_info_command_prefixes"] if str(item).strip()]
        if data.get("max_tokens"):
            reply.max_tokens = int(data["max_tokens"])
        if data.get("timeout_seconds"):
            reply.timeout_seconds = float(data["timeout_seconds"])

    def _save_ai_settings(self) -> None:
        payload = {
            "model": self.config.reply_provider.model,
            "reasoning_effort": self.config.reply.reasoning_effort,
            "reasoning_summary": self.config.reply.reasoning_summary,
            "text_verbosity": self.config.reply.text_verbosity,
            "web_search": self.config.reply.web_search,
            "image_detail": self.config.reply.image_detail,
            "message_info_enabled": self.config.reply.message_info_enabled,
            "message_info_command_prefixes": self.config.reply.message_info_command_prefixes,
            "max_tokens": self.config.reply.max_tokens,
            "timeout_seconds": self.config.reply.timeout_seconds,
        }
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.settings_path)
        self._sync_card_config()

    def _sync_card_config(self) -> None:
        self.card.config = {
            "provider": self.config.reply_provider.name,
            "provider_type": self.config.reply_provider.provider_type,
            "model": self.config.reply_provider.model,
            "base_url": self.config.reply_provider.base_url,
            "reply": asdict(self.config.reply),
            "settings_store": str(self.settings_path),
        }

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute() or self.project_root is None:
            return path
        return self.project_root / path


def strip_first_wake_word(text: str, wake_words: list[str]) -> str | None:
    for wake_word in sorted((word for word in wake_words if word), key=len, reverse=True):
        if wake_word in text:
            return text.replace(wake_word, "", 1).strip()
    return None


def extract_ai_prompt(text: str, is_reply: bool, config: AIReplyConfig) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    for prefix in sorted((item for item in config.command_prefixes if item), key=len, reverse=True):
        if stripped == prefix:
            return ""
        if stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\n"):
            return stripped[len(prefix) :].strip()
    wake_prompt = strip_first_wake_word(stripped, config.wake_words)
    if wake_prompt is not None:
        return wake_prompt
    if is_reply:
        for trigger in sorted((item for item in config.reply_triggers if item), key=len, reverse=True):
            if stripped == trigger:
                return ""
            if stripped.startswith(trigger + " ") or stripped.startswith(trigger + "\n"):
                return stripped[len(trigger) :].strip()
    return None


def command_matches_prefix(text: str, prefixes: list[str]) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    for prefix in sorted((item.strip() for item in prefixes if item.strip()), key=len, reverse=True):
        if stripped == prefix or stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\n"):
            return True
    return False


async def build_message_info_payload(event: Any, message: Any) -> dict[str, Any]:
    sender = await _resolve_message_sender(message)
    chat = await _resolve_message_chat(message)
    if chat is None:
        chat = await _resolve_event_chat(event)

    payload: dict[str, Any] = {
        "_": "Message",
        "id": getattr(message, "id", None),
        "from_user": entity_info(sender),
        "date": stringify_value(getattr(message, "date", None)),
        "chat": entity_info(chat),
        "chat_id": getattr(message, "chat_id", getattr(event, "chat_id", None)),
        "sender_id": getattr(message, "sender_id", None),
        "text": _message_text(message),
        "media": media_info(message),
        "grouped_id": getattr(message, "grouped_id", None),
        "outgoing": bool(getattr(message, "out", False)),
        "mentioned": bool(getattr(message, "mentioned", False)),
        "silent": bool(getattr(message, "silent", False)),
        "pinned": bool(getattr(message, "pinned", False)),
        "post": bool(getattr(message, "post", False)),
        "edit_date": stringify_value(getattr(message, "edit_date", None)),
        "reply_to_msg_id": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
        "raw": {
            "message": telegram_object_to_plain(message, max_depth=3),
            "from_user": telegram_object_to_plain(sender, max_depth=3),
            "chat": telegram_object_to_plain(chat, max_depth=3),
        },
    }
    return strip_empty_values(payload)


async def _resolve_message_sender(message: Any) -> Any:
    sender = getattr(message, "sender", None) or getattr(message, "from_user", None)
    if sender is not None:
        return sender
    if hasattr(message, "get_sender"):
        try:
            return await message.get_sender()
        except Exception:
            logger.exception("Failed to resolve message sender for /msg")
    return None


async def _resolve_message_chat(message: Any) -> Any:
    chat = getattr(message, "chat", None)
    if chat is not None:
        return chat
    if hasattr(message, "get_chat"):
        try:
            return await message.get_chat()
        except Exception:
            logger.exception("Failed to resolve message chat for /msg")
    return None


async def _resolve_event_chat(event: Any) -> Any:
    if hasattr(event, "get_chat"):
        try:
            return await event.get_chat()
        except Exception:
            logger.exception("Failed to resolve event chat for /msg")
    return None


def entity_info(entity: Any) -> dict[str, Any] | None:
    if entity is None:
        return None
    return strip_empty_values(
        {
            "_": entity.__class__.__name__,
            "id": getattr(entity, "id", None),
            "is_self": bool(getattr(entity, "is_self", False)),
            "is_contact": bool(getattr(entity, "contact", getattr(entity, "is_contact", False))),
            "is_mutual_contact": bool(getattr(entity, "mutual_contact", False)),
            "is_deleted": bool(getattr(entity, "deleted", False)),
            "is_bot": bool(getattr(entity, "bot", False)),
            "is_restricted": bool(getattr(entity, "restricted", False)),
            "is_support": bool(getattr(entity, "support", False)),
            "is_premium": bool(getattr(entity, "premium", False)),
            "first_name": getattr(entity, "first_name", None),
            "last_name": getattr(entity, "last_name", None),
            "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None),
            "status": stringify_value(getattr(entity, "status", None)),
            "dc_id": getattr(getattr(entity, "photo", None), "dc_id", None) or getattr(entity, "dc_id", None),
            "megagroup": getattr(entity, "megagroup", None),
            "broadcast": getattr(entity, "broadcast", None),
            "verified": getattr(entity, "verified", None),
            "scam": getattr(entity, "scam", None),
            "fake": getattr(entity, "fake", None),
        }
    )


def media_info(message: Any) -> dict[str, Any] | None:
    media = getattr(message, "media", None)
    document = telegram_media.media_document(message)
    file = getattr(message, "file", None)
    sticker = getattr(message, "sticker", None)
    if media is None and document is None and file is None and sticker is None:
        return None

    info = {
        "_": media.__class__.__name__ if media is not None else None,
        "mime_type": telegram_media.media_mime_type(message),
        "file_name": telegram_media.media_file_name(message),
        "file_suffix": telegram_media.media_file_suffix(message),
        "file_size": media_size_bytes(message),
        "is_sticker": telegram_media.media_has_sticker_attribute(message) or bool(sticker),
        "is_tgs_sticker": telegram_media.media_is_tgs_sticker(message),
        "is_motion": telegram_media.media_is_motion(message),
        "width": getattr(file, "width", None) if file is not None else getattr(document, "w", None),
        "height": getattr(file, "height", None) if file is not None else getattr(document, "h", None),
        "duration": getattr(file, "duration", None) if file is not None else getattr(document, "duration", None),
        "sticker": telegram_object_to_plain(sticker, max_depth=2) if sticker is not None else None,
        "document": telegram_object_to_plain(document, max_depth=2) if document is not None else None,
    }
    return strip_empty_values(info)


def telegram_object_to_plain(obj: Any, max_depth: int = 3) -> Any:
    return make_json_safe(obj, max_depth=max_depth)


def make_json_safe(value: Any, max_depth: int = 3, max_string: int = 600, max_items: int = 40) -> Any:
    if max_depth < 0:
        return stringify_value(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return truncate_plain_string(value, max_string)
    if isinstance(value, bytes):
        return f"<bytes len={len(value)}>"
    if isinstance(value, (list, tuple, set)):
        items = [make_json_safe(item, max_depth - 1, max_string, max_items) for item in list(value)[:max_items]]
        if len(value) > max_items:
            items.append(f"... {len(value) - max_items} more")
        return items
    if isinstance(value, dict):
        items: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                items["..."] = f"{len(value) - max_items} more"
                break
            items[str(key)] = make_json_safe(item, max_depth - 1, max_string, max_items)
        return strip_empty_values(items)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ", timespec="seconds")
        except TypeError:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            if isinstance(data, dict) and "_" not in data:
                data = {"_": value.__class__.__name__, **data}
            return make_json_safe(data, max_depth - 1, max_string, max_items)
        except Exception:
            pass
    return truncate_plain_string(str(value), max_string)


def strip_empty_values(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def truncate_plain_string(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"...<truncated {len(value) - limit} chars>"


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ", timespec="seconds")
        except TypeError:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def format_message_info_block(payload: dict[str, Any]) -> str:
    json_text = json.dumps(payload, ensure_ascii=False, indent=4, default=str)
    text = "<blockquote expandable>" + html.escape(json_text, quote=False) + "</blockquote>"
    if len(text) <= TELEGRAM_SAFE_TEXT_LIMIT:
        return text

    compact_payload = dict(payload)
    compact_payload.pop("raw", None)
    json_text = json.dumps(compact_payload, ensure_ascii=False, indent=4, default=str)
    text = "<blockquote expandable>" + html.escape(json_text, quote=False) + "</blockquote>"
    if len(text) <= TELEGRAM_SAFE_TEXT_LIMIT:
        return text
    return "<blockquote expandable>" + html.escape(truncate_plain_string(json_text, 3200), quote=False) + "</blockquote>"


def format_message_info_hint(config: AIReplyConfig) -> str:
    command = next((item for item in config.message_info_command_prefixes if item), "/msg")
    return f"请回复一条消息后发送 <code>{html.escape(command)}</code> 查看该用户和该消息的信息。"


async def collect_short_context(event: Any, config: AIReplyConfig) -> tuple[str, str]:
    message = _event_message(event)
    reply_text = ""
    if message is not None and getattr(message, "is_reply", False):
        replied = await _get_reply_message(message)
        if replied and _message_text(replied):
            reply_text = _message_text(replied)

    context_text = await collect_context_with_reply_text(event, config, reply_text)
    return context_text, reply_text


async def collect_context_with_reply_text(event: Any, config: AIReplyConfig, reply_text: str = "") -> str:
    message = _event_message(event)
    recent_lines: list[str] = []
    client = getattr(event, "client", None)
    chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
    message_id = getattr(message, "id", None)
    if client is not None and chat_id is not None and message_id is not None:
        try:
            async for item in client.iter_messages(chat_id, limit=config.context_limit, max_id=message_id):
                item_text = _message_text(item)
                if item_text:
                    speaker = "我" if getattr(item, "out", False) else f"用户{getattr(item, 'sender_id', '')}"
                    recent_lines.append(f"{speaker}: {item_text}")
        except Exception:
            logger.exception("Failed to collect short AI context")

    recent_lines.reverse()
    context_parts: list[str] = []
    if recent_lines:
        context_parts.append("最近聊天上下文：\n" + "\n".join(recent_lines))
    if reply_text:
        context_parts.append("被回复的消息：\n" + reply_text)
    return "\n\n".join(context_parts)


def media_is_motion(message: Any) -> bool:
    return telegram_media.media_is_motion(message)


def media_may_be_video(message: Any) -> bool:
    return telegram_media.media_may_be_video(message)


def media_is_tgs_sticker(message: Any) -> bool:
    return telegram_media.media_is_tgs_sticker(message)


def media_file_suffix(message: Any) -> str:
    return telegram_media.media_file_suffix(message)


def build_developer_prompt(config: AIReplyConfig) -> str:
    parts = [
        "你是一个运行在 Telegram 群聊中的 AI 助手。",
        "默认使用简体中文回答，除非用户明确要求其他语言。",
        "回答要准确、简洁、可执行；必要时分点说明。",
    ]
    if config.web_search:
        parts.extend(
            [
                "只有在需要最新信息、实时信息、核实事实，或用户提供 URL 需要核对时，才使用 web_search 工具。",
                "如果使用了网页信息，请尽量在回答末尾保留可点击来源。",
            ]
        )
    return "\n".join(parts)


def supports_responses_controls(model_name: str) -> bool:
    name = (model_name or "").lower()
    return name.startswith("gpt-5") or name.startswith("o3") or name.startswith("o4")


def format_markdown_for_telegram(text: str) -> str:
    if not text:
        return "<i>（模型未返回可显示文本）</i>"
    return html.escape(text)


def format_ai_group_message(
    question: str,
    answer: str,
    model: str,
    quoted_text: str = "",
    answer_is_html: bool = False,
    powered_by: str = "",
    token_stats: str = "",
    elapsed_seconds: float | None = None,
    reasoning_html: str = "",
    service_label: str = "OpenAI Responses",
) -> str:
    safe_question = html.escape(truncate_text(question.strip() or "继续根据上下文回答", 700))
    safe_answer = answer.strip() if answer_is_html else html.escape(truncate_text(answer.strip(), 2600))
    safe_model = html.escape(model.strip() or "unknown")
    safe_service = html.escape(service_label.strip() or "OpenAI Responses")
    parts: list[str] = []
    if quoted_text.strip():
        safe_quoted = html.escape(truncate_text(quoted_text.strip(), 900))
        parts.append("◔_◔ 引用消息：\n\n" f"<blockquote expandable>{safe_quoted}</blockquote>")
    parts.append("◔_◔ 你问：\n\n" f"<blockquote expandable>{safe_question}</blockquote>")
    parts.append(f"✨ <b>{safe_service}：</b>\n" f"<blockquote expandable>{safe_answer}</blockquote>")
    if reasoning_html.strip():
        parts.append("🧠 <b>思考摘要：</b>\n" f"<blockquote expandable>{reasoning_html}</blockquote>")
    parts.append("──────────")
    footer_lines = [f"<i>🚀 {html.escape(powered_by) if powered_by else safe_service + ' × ' + safe_model}</i>"]
    if token_stats:
        footer_lines.append(f"<i>📊 {html.escape(token_stats)}</i>")
    if elapsed_seconds is not None:
        footer_lines.append(f"<i>⏱️ Time: {max(0.0, elapsed_seconds):.1f}s</i>")
    parts.append("\n".join(footer_lines))
    parts.append(f"◆ 当前模型：<code>{safe_model}</code>")
    return "\n\n".join(parts)


def format_ai_setting_message(setting_name: str, value: Any) -> str:
    return f"<b>AI 设置已更新</b>\n{html.escape(setting_name)}: <code>{html.escape(str(value))}</code>"


def parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "1", "yes", "y"}:
        return True
    if normalized in {"off", "false", "0", "no", "n"}:
        return False
    return None


def _media_mime_type(message: Any) -> str:
    return telegram_media.media_mime_type(message)


def _media_file_name(message: Any) -> str:
    return telegram_media.media_file_name(message)


def _reply_config_from_dict(data: dict[str, Any]) -> AIReplyConfig:
    return AIReplyConfig(
        system_prompt=str(data.get("system_prompt") or AIReplyConfig.system_prompt),
        owner_user_ids=[int(item) for item in data.get("owner_user_ids", []) if str(item).strip()],
        command_prefixes=_clean_list(data.get("command_prefixes")),
        wake_words=_clean_list(data.get("wake_words")),
        reply_triggers=_clean_list(data.get("reply_triggers")),
        context_limit=int(data.get("context_limit") or 6),
        timeout_seconds=float(data.get("timeout_seconds") or 180.0),
        max_tokens=int(data.get("max_tokens") or 25000),
        temperature=float(data.get("temperature") or 0.7),
        reasoning_effort=str(data.get("reasoning_effort") or "none"),
        reasoning_summary=bool(data.get("reasoning_summary", True)),
        text_verbosity=str(data.get("text_verbosity") or "medium"),
        web_search=bool(data.get("web_search", True)),
        image_detail=str(data.get("image_detail") or "original"),
        message_info_enabled=bool(data.get("message_info_enabled", True)),
        message_info_command_prefixes=_clean_list(data.get("message_info_command_prefixes")) or ["/msg"],
        settings_store=str(data.get("settings_store") or "runtime/data/ai_settings.json"),
    )


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
