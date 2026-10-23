from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot.config import AIConfig, AIDecryptConfig, AIDecryptTemplateConfig
from telegram_bot.shared.ai_responses import (
    AsyncOpenAI,
    collect_image_inputs_for_responses,
    collect_response_text_and_sources,
    extract_usage_counts,
)
from telegram_bot.shared.ai_messages import (
    aclose_anthropic,
    anthropic_create_message,
    anthropic_image_block,
    build_openai_chat_messages,
    collect_anthropic_text_and_sources,
    collect_chat_completions_text_and_sources,
    is_anthropic_provider,
    is_chat_completions_provider,
    make_async_anthropic_client,
)
from telegram_bot.shared.telegram_io import (
    event_message as _event_message,
    is_outgoing as _is_outgoing,
    message_text as _message_text,
)
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)

CLAIM_TTL_SECONDS = 48 * 60 * 60
SolverFunc = Callable[[str, list[dict[str, str]], AIDecryptTemplateConfig], Awaitable[str] | str]


class AIDecryptModule:
    def __init__(
        self,
        card: ModuleCard,
        config: AIDecryptConfig,
        ai_config: AIConfig,
        project_root: Path | None = None,
        solver_func: SolverFunc | None = None,
        now_func: Any = time.time,
    ) -> None:
        self.card = card
        self.config = config
        self.ai_config = ai_config
        self.project_root = project_root
        self.solver_func = solver_func
        self.now_func = now_func
        self.state_path = self._resolve_path(self.config.state_store)
        self.usage_path = self._resolve_path("runtime/data/ai_usage.jsonl")
        self.claimed_ids = self._load_claimed_ids()
        self._processing_ids: set[tuple[str, str]] = set()
        self._processing_lock = asyncio.Lock()
        self._sync_card_config()

    async def start(self) -> None:
        self.cleanup_claimed_ids()
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        message = _event_message(event)
        text = _message_text(message or event)
        if not text:
            return HandlerResult.ignored(self.card.id)

        template = self.match_template(text)
        if template is None:
            return HandlerResult.ignored(self.card.id)

        if template.require_media and not bool(getattr(message, "media", None)):
            logger.info("AI decrypt template matched but message has no media: template=%s", template.id)
            return HandlerResult.ignored(self.card.id)

        puzzle_id = self.extract_puzzle_id(event, text, template)
        if self._is_claimed(template.id, puzzle_id):
            logger.info("AI decrypt puzzle already handled: template=%s id=%s", template.id, puzzle_id)
            return HandlerResult.ignored(self.card.id)
        if not await self._reserve_processing(template.id, puzzle_id):
            logger.info("AI decrypt puzzle already in progress: template=%s id=%s", template.id, puzzle_id)
            return HandlerResult.ignored(self.card.id)

        try:
            image_inputs, media_error = await collect_image_inputs_for_responses(event, "")
            if media_error:
                logger.warning("AI decrypt media input hint: %s", media_error)
            if template.require_media and not image_inputs:
                return HandlerResult.failed(self.card.id, "matched template but no image input was collected")

            answer = await self.solve(text, image_inputs, template)

            answer = sanitize_answer(answer)
            if not answer:
                return HandlerResult.failed(self.card.id, "AI decrypt returned empty answer")
            if answer.lstrip().startswith("/"):
                logger.warning("AI decrypt answer looked like a command, skipped: %s", answer[:120])
                return HandlerResult.ignored(self.card.id)

            self._mark_claimed(template.id, puzzle_id)
            delay_seconds = max(0, int(self.config.send_delay_ms or 0)) / 1000
            if delay_seconds:
                logger.info("AI decrypt send delayed: template=%s id=%s delay_ms=%s", template.id, puzzle_id, self.config.send_delay_ms)
                await asyncio.sleep(delay_seconds)
            await respond_to_message(event, answer)
            logger.info("AI decrypt answer sent: template=%s id=%s answer=%s", template.id, puzzle_id, answer[:120])
            return HandlerResult.handled(
                self.card.id,
                "ai decrypt answer sent",
                {"template_id": template.id, "template_name": template.name, "puzzle_id": puzzle_id, "answer": answer},
            )
        except Exception as exc:
            logger.exception("AI decrypt failed: %s", exc)
            return HandlerResult.failed(self.card.id, str(exc))
        finally:
            self._release_processing(template.id, puzzle_id)

    def match_template(self, text: str) -> AIDecryptTemplateConfig | None:
        folded = text.casefold()
        compact_folded = compact_match_text(folded)
        for template in self.config.templates:
            if not template.enabled:
                continue
            keywords = [keyword.casefold().strip() for keyword in template.trigger_keywords if keyword.strip()]
            if not keywords:
                continue
            if not all(keyword in folded or compact_match_text(keyword) in compact_folded for keyword in keywords):
                continue
            return template
        return None

    def extract_puzzle_id(self, event: Any, text: str, template: AIDecryptTemplateConfig) -> str:
        for marker in template.id_markers:
            value = extract_after_marker(text, marker)
            if value:
                return first_token(value)
        message = _event_message(event)
        chat_id = getattr(message, "chat_id", getattr(event, "chat_id", "chat"))
        message_id = getattr(message, "id", getattr(event, "id", "message"))
        return f"{chat_id}:{message_id}"

    async def solve(self, text: str, image_inputs: list[dict[str, str]], template: AIDecryptTemplateConfig) -> str:
        if self.solver_func is not None:
            result = self.solver_func(text, image_inputs, template)
            if hasattr(result, "__await__"):
                return str(await result)  # type: ignore[arg-type]
            return str(result)
        return await self._call_ai_solver(text, image_inputs, template)

    async def _call_ai_solver(self, text: str, image_inputs: list[dict[str, str]], template: AIDecryptTemplateConfig) -> str:
        provider = self.ai_config.reply_provider
        if is_anthropic_provider(provider.provider_type):
            return await self._call_anthropic_solver(text, image_inputs, template)
        if is_chat_completions_provider(provider.provider_type):
            return await self._call_openai_chat_completions_solver(text, image_inputs, template)
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt")
        if not provider.api_key:
            raise ValueError("AI 解密需要配置 AI 服务 Key")
        if not provider.model:
            raise ValueError("AI 解密需要配置 AI 服务模型")

        client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url.rstrip("/"), timeout=self.config.timeout_seconds)
        user_content: list[dict[str, Any]] = [{"type": "input_text", "text": text.strip()}]
        for image_input in image_inputs:
            image_url = image_input.get("url", "")
            if image_url:
                user_content.append({"type": "input_image", "image_url": image_url, "detail": self.config.image_detail})
        request_kwargs = {
            "model": provider.model,
            "input": [
                {"role": "user", "content": user_content},
            ],
            "store": False,
            "max_output_tokens": self.config.max_tokens,
        }
        logger.info("AI decrypt request started template=%s model=%s images=%s", template.id, provider.model, len(image_inputs))
        started_at = time.monotonic()
        try:
            response = await client.responses.create(**request_kwargs)
            self._record_ai_usage("ai_decrypt", "responses", provider.model, True, started_at, response)
        except Exception as exc:
            self._record_ai_usage("ai_decrypt", "responses", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            try:
                await client.close()
            except Exception:
                pass
        answer, _sources = collect_response_text_and_sources(response)
        return answer

    async def _call_openai_chat_completions_solver(
        self,
        text: str,
        image_inputs: list[dict[str, str]],
        template: AIDecryptTemplateConfig,
    ) -> str:
        provider = self.ai_config.reply_provider
        if AsyncOpenAI is None:
            raise RuntimeError("缺少 openai 依赖，请重新安装 requirements.txt")
        if not provider.api_key:
            raise ValueError("AI 解密需要配置 AI 服务 Key")
        if not provider.model:
            raise ValueError("AI 解密需要配置 AI 服务模型")

        client_kwargs: dict[str, Any] = {"api_key": provider.api_key, "timeout": self.config.timeout_seconds}
        if provider.base_url.strip():
            client_kwargs["base_url"] = provider.base_url.rstrip("/")
        client = AsyncOpenAI(**client_kwargs)
        request_kwargs = {
            "model": provider.model,
            "messages": build_openai_chat_messages(
                text.strip(),
                image_inputs,
                self.config.image_detail,
            ),
            "max_tokens": self.config.max_tokens,
        }
        logger.info(
            "AI decrypt request started template=%s model=%s images=%s provider=chat_completions",
            template.id,
            provider.model,
            len(image_inputs),
        )
        started_at = time.monotonic()
        try:
            response = await client.chat.completions.create(**request_kwargs)
            self._record_ai_usage("ai_decrypt", "chat_completions", provider.model, True, started_at, response)
        except Exception as exc:
            self._record_ai_usage("ai_decrypt", "chat_completions", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            try:
                await client.close()
            except Exception:
                pass
        answer, _sources = collect_chat_completions_text_and_sources(response)
        return answer

    async def _call_anthropic_solver(self, text: str, image_inputs: list[dict[str, str]], template: AIDecryptTemplateConfig) -> str:
        provider = self.ai_config.reply_provider
        if not provider.api_key:
            raise ValueError("AI 解密需要配置 AI 服务 Key")
        if not provider.model:
            raise ValueError("AI 解密需要配置 AI 服务模型")

        client = make_async_anthropic_client(provider.api_key, provider.base_url, self.config.timeout_seconds)
        # 与 OpenAI 路径一致：只发送原始题面文本与图片，不下发模板 prompt。
        user_content: list[dict[str, Any]] = [{"type": "text", "text": text.strip()}]
        for image_input in image_inputs:
            image_block = anthropic_image_block(image_input.get("url", ""))
            if image_block is not None:
                user_content.append(image_block)
        request_kwargs = {
            "model": provider.model,
            "max_tokens": self.config.max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        logger.info("AI decrypt request started template=%s model=%s images=%s provider=anthropic", template.id, provider.model, len(image_inputs))
        started_at = time.monotonic()
        try:
            message = await anthropic_create_message(client, request_kwargs)
            self._record_ai_usage("ai_decrypt", "messages", provider.model, True, started_at, message)
        except Exception as exc:
            self._record_ai_usage("ai_decrypt", "messages", provider.model, False, started_at, error=str(exc))
            raise
        finally:
            await aclose_anthropic(client)
        answer, _sources = collect_anthropic_text_and_sources(message)
        return answer

    def update_config(self, values: dict[str, Any]) -> None:
        templates = values.get("templates")
        if isinstance(templates, list):
            self.config.templates = [
                template_from_dict(item)
                for item in templates
                if isinstance(item, dict)
            ]
        if "timeout_seconds" in values:
            self.config.timeout_seconds = max(5.0, float(values.get("timeout_seconds") or 120.0))
        if "max_tokens" in values:
            self.config.max_tokens = max(16, min(int(values.get("max_tokens") or 512), 4096))
        if "image_detail" in values:
            self.config.image_detail = str(values.get("image_detail") or "original")
        if "send_delay_ms" in values:
            self.config.send_delay_ms = max(0, min(int(values.get("send_delay_ms") or 0), 60_000))
        if "state_store" in values:
            self.config.state_store = str(values.get("state_store") or "runtime/data/ai_decrypt_claimed_ids.json")
            self.state_path = self._resolve_path(self.config.state_store)
            self.claimed_ids = self._load_claimed_ids()
        self._sync_card_config()
        logger.info("AI decrypt config updated: templates=%s delay_ms=%s", self._enabled_template_count(), self.config.send_delay_ms)

    def cleanup_claimed_ids(self) -> None:
        now = self.now_func()
        changed = False
        for template_id in list(self.claimed_ids.keys()):
            entries = self.claimed_ids.get(template_id, {})
            fresh = {
                puzzle_id: claimed_at
                for puzzle_id, claimed_at in entries.items()
                if is_fresh_claim(claimed_at, now)
            }
            if fresh != entries:
                self.claimed_ids[template_id] = fresh
                changed = True
        if changed:
            self._save_claimed_ids()

    def _enabled_template_count(self) -> int:
        return sum(1 for template in self.config.templates if template.enabled)

    def _is_claimed(self, template_id: str, puzzle_id: str) -> bool:
        self.cleanup_claimed_ids()
        entries = self.claimed_ids.get(template_id, {})
        return is_fresh_claim(entries.get(puzzle_id), self.now_func())

    async def _reserve_processing(self, template_id: str, puzzle_id: str) -> bool:
        key = (template_id, puzzle_id)
        async with self._processing_lock:
            if self._is_claimed(template_id, puzzle_id) or key in self._processing_ids:
                return False
            self._processing_ids.add(key)
            return True

    def _release_processing(self, template_id: str, puzzle_id: str) -> None:
        self._processing_ids.discard((template_id, puzzle_id))

    def _mark_claimed(self, template_id: str, puzzle_id: str) -> None:
        self.cleanup_claimed_ids()
        self.claimed_ids.setdefault(template_id, {})[puzzle_id] = self.now_func()
        self._save_claimed_ids()

    def _load_claimed_ids(self) -> dict[str, dict[str, float]]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load AI decrypt claimed ids, starting empty")
            return {}
        templates = data.get("templates", {}) if isinstance(data, dict) else {}
        loaded: dict[str, dict[str, float]] = {}
        if isinstance(templates, dict):
            for template_id, entries in templates.items():
                if isinstance(entries, dict):
                    loaded[str(template_id)] = {
                        str(puzzle_id): float(claimed_at)
                        for puzzle_id, claimed_at in entries.items()
                        if as_float(claimed_at) is not None
                    }
        return loaded

    def _save_claimed_ids(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "ttl_seconds": CLAIM_TTL_SECONDS, "templates": self.claimed_ids}
        self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _sync_card_config(self) -> None:
        self.card.config = {
            **asdict(self.config),
            "template_count": len(self.config.templates),
            "enabled_template_count": self._enabled_template_count(),
            "claimed_id_ttl_hours": 48,
            "provider": self.ai_config.reply_provider.name,
            "provider_type": self.ai_config.reply_provider.provider_type,
            "model": self.ai_config.reply_provider.model,
        }

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute() or self.project_root is None:
            return path
        return self.project_root / path

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
            "feature": feature,
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
            logger.exception("Failed to write AI decrypt usage stats")


async def respond_to_message(event: Any, answer: str) -> None:
    message = _event_message(event)
    target = message or event
    if hasattr(target, "respond"):
        await target.respond(answer)
        return
    if hasattr(event, "respond"):
        await event.respond(answer)
        return
    client = getattr(event, "client", None)
    chat_id = getattr(message, "chat_id", getattr(event, "chat_id", None))
    if client is not None and chat_id is not None and hasattr(client, "send_message"):
        await client.send_message(chat_id, answer)


def sanitize_answer(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("```"):
        value = value.strip("`").strip()
    for prefix in ("答案：", "答案:", "最终答案：", "最终答案:"):
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    return " ".join(value.split())[:200]


def template_from_dict(data: dict[str, Any]) -> AIDecryptTemplateConfig:
    return AIDecryptTemplateConfig(
        id=str(data.get("id") or "").strip(),
        name=str(data.get("name") or "").strip(),
        enabled=bool(data.get("enabled", True)),
        trigger_keywords=clean_list(data.get("trigger_keywords")),
        id_markers=clean_list(data.get("id_markers")),
        require_media=bool(data.get("require_media", True)),
        prompt=str(data.get("prompt") or "").strip(),
    )


def clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def compact_match_text(value: str) -> str:
    return "".join(str(value or "").split())


def extract_after_marker(text: str, marker: str) -> str:
    marker = marker.strip()
    if not marker:
        return ""
    marker_folded = marker.casefold()
    for line in text.splitlines():
        position = line.casefold().find(marker_folded)
        if position < 0:
            continue
        return line[position + len(marker) :].strip().lstrip(" \t:：").strip()
    return ""


def first_token(value: str) -> str:
    return value.strip().split()[0] if value.strip() else ""


def is_fresh_claim(value: Any, now: float) -> bool:
    claimed_at = as_float(value)
    return claimed_at is not None and now - claimed_at < CLAIM_TTL_SECONDS


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
