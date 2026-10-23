from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import mimetypes
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from telegram_bot.config import AIConfig, AIImageConfig
from telegram_bot.shared.ai_responses import extract_usage_counts
from telegram_bot.shared.ai_messages import (
    collect_anthropic_text_and_sources,
    is_anthropic_provider,
    make_sync_anthropic_client,
)
from telegram_bot.shared.telegram_io import safe_delete_message, safe_edit_message
from telegram_bot.shared.telegram_media import (
    extract_first_frame_from_path_as_jpeg,
    media_is_motion,
    media_is_tgs_sticker,
)
from telegram_bot.shared.contracts import HandlerResult
from telegram_bot.shared.net import ensure_http_url

from .base import ModuleCard

logger = logging.getLogger(__name__)

AUTO_IMAGE_RATIO = "auto"
TELEGRAM_PHOTO_SIZE_LIMIT = 10 * 1024 * 1024
MAX_CONTEXT_TEXT_CHARS = 8000
XAI_IMAGINE_PROVIDER_TYPES = frozenset({"xai", "xai-compatible", "xai-imagine", "grok-imagine"})
IMAGE_DOWNLOAD_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
}
XAI_IMAGINE_ASPECT_RATIOS = frozenset(
    {
        "auto",
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
        "2:1",
        "1:2",
        "19.5:9",
        "9:19.5",
        "20:9",
        "9:20",
        "21:9",
        "5:2",
    }
)


class ImageProviderConfigError(ValueError):
    """Raised when local image-provider settings cannot form a valid request."""


class ImageProviderRequestError(RuntimeError):
    """Raised when the image provider rejects an otherwise valid request."""

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]


class AIImageModule:
    def __init__(self, card: ModuleCard, config: AIConfig, project_root: Path | None = None) -> None:
        self.card = card
        self.config = config
        self.project_root = project_root
        self.usage_path = self._resolve_path("runtime/data/ai_usage.jsonl")
        self.output_dir = self._resolve_path(self.config.image.output_dir)
        self.tmp_dir = self._resolve_path("runtime/tmp")
        self.settings_path = self._resolve_path(self.config.image.settings_store)
        self._load_image_settings()
        self._sync_card_config()

    async def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, event: Any) -> HandlerResult:
        if not self.config.image_provider.enabled:
            return HandlerResult.ignored(self.card.id)
        if not _is_outgoing(event):
            return HandlerResult.ignored(self.card.id)

        message = _event_message(event)
        if await self._handle_image_setting_command(message):
            return HandlerResult.handled(self.card.id, "image setting updated")

        prompt = extract_image_prompt(_message_text(message), self.config.image)
        if prompt is None:
            return HandlerResult.ignored(self.card.id)

        try:
            await self._handle_image_generation(event, prompt)
        except Exception as exc:
            logger.exception("AI image generation failed: %s", exc)
            return HandlerResult.failed(self.card.id, str(exc))
        return HandlerResult.handled(self.card.id, "image generated", {"prompt": prompt})

    def update_config(self, values: dict[str, Any]) -> None:
        image_values = values.get("image")
        should_save_runtime_settings = False
        if isinstance(image_values, dict):
            self.config.image = _image_config_from_dict({**asdict(self.config.image), **image_values})
            should_save_runtime_settings = any(key in image_values for key in ("size", "ratio", "send_mode"))
        provider_values = values.get("image_provider")
        if isinstance(provider_values, dict):
            for key in ("name", "provider_type", "base_url", "model"):
                if key in provider_values:
                    setattr(self.config.image_provider, key, str(provider_values.get(key) or ""))
                    if key == "model":
                        should_save_runtime_settings = True
            if "enabled" in provider_values:
                self.config.image_provider.enabled = bool(provider_values["enabled"])
            if str(provider_values.get("api_key") or "").strip():
                self.config.image_provider.api_key = str(provider_values["api_key"]).strip()
        self.output_dir = self._resolve_path(self.config.image.output_dir)
        self.settings_path = self._resolve_path(self.config.image.settings_store)
        if should_save_runtime_settings:
            self._save_image_settings()
        self._sync_card_config()

    def reload_runtime_settings(self) -> None:
        self._load_image_settings()
        self._sync_card_config()

    async def _handle_image_generation(self, event: Any, prompt: str) -> None:
        message = _event_message(event)
        initial_prompt = prompt or "基于引用内容生成图片"
        await safe_edit_message(
            message,
            format_image_status_message(initial_prompt, "正在读取引用内容……", self.image_model, self.config.image.ratio, self.config.image.size),
            parse_mode="html",
        )

        replied_message = await _get_reply_message(message)
        effective_prompt, reference_image_path, reference_note = await self._collect_image_generation_context(message, prompt, replied_message)
        if not prompt and not reference_image_path and not reference_note:
            await safe_edit_message(
                message,
                format_image_status_message(
                    "",
                    "请在 /draw 后面写上作图提示词，或回复文字/图片后触发生图。",
                    self.image_model,
                    self.config.image.ratio,
                    self.config.image.size,
                ),
                parse_mode="html",
            )
            return

        display_prompt = prompt or ("基于引用内容生成图片" if reference_note else "未提供提示词")
        status = "正在基于引用内容生成图片……" if reference_note else "正在生成图片……"
        logger.info(
            "Trigger image generation chat_id=%s message_id=%s model=%s size=%s ratio=%s prompt_len=%s reference=%s",
            getattr(message, "chat_id", None),
            getattr(message, "id", None),
            self.image_model,
            self.config.image.size,
            self.config.image.ratio,
            len(effective_prompt),
            reference_note or "none",
        )
        await safe_edit_message(
            message,
            format_image_status_message(display_prompt, status, self.image_model, self.config.image.ratio, self.config.image.size),
            parse_mode="html",
        )

        output_path = self.output_dir / f"tg_image_{getattr(message, 'chat_id', 'chat')}_{getattr(message, 'id', int(time.time()))}.png"
        try:
            image_path = await asyncio.to_thread(self._generate_image_with_openai_compatible_api, effective_prompt, output_path, reference_image_path)
        except ImageProviderConfigError as exc:
            logger.warning("AI image provider configuration error: %s", exc)
            await safe_edit_message(
                message,
                format_image_status_message(
                    display_prompt,
                    f"配置错误：{exc}",
                    self.image_model,
                    self.config.image.ratio,
                    self.config.image.size,
                ),
                parse_mode="html",
            )
            _unlink_quietly(reference_image_path)
            return
        except ImageProviderRequestError as exc:
            logger.warning("AI image provider rejected request: %s", exc)
            await safe_edit_message(
                message,
                format_image_status_message(
                    display_prompt,
                    f"请求失败：{exc}",
                    self.image_model,
                    self.config.image.ratio,
                    self.config.image.size,
                ),
                parse_mode="html",
            )
            _unlink_quietly(reference_image_path)
            return
        except Exception as exc:
            if reference_image_path and not is_timeout_error(exc):
                logger.exception("Reference-image edit failed, trying describe-and-generate fallback: %s", exc)
                try:
                    reference_description = await asyncio.to_thread(self._call_ai_describe_reference_image, reference_image_path, prompt)
                    fallback_prompt = (
                        "请根据以下参考图描述进行生图，并执行用户修改要求。\n\n"
                        f"参考图描述：\n{reference_description}\n\n"
                        f"用户修改要求：\n{prompt or '根据参考图生成合适图片'}"
                    )
                    image_path = await asyncio.to_thread(self._generate_image_with_openai_compatible_api, fallback_prompt, output_path, None)
                except Exception as fallback_exc:
                    logger.exception("Reference fallback image generation failed: %s", fallback_exc)
                    await safe_delete_message(message, "image_generation_cleanup")
                    _unlink_quietly(reference_image_path)
                    return
            else:
                logger.exception("Image generation failed; deleting status message: %s", exc)
                await safe_delete_message(message, "image_generation_cleanup")
                if reference_image_path:
                    _unlink_quietly(reference_image_path)
                return

        if reference_image_path:
            _unlink_quietly(reference_image_path)

        caption_prompt = display_prompt if not reference_note else f"{display_prompt}（{reference_note}）"
        caption = format_image_caption(caption_prompt, self.image_model, self.config.image.ratio, self.config.image.size)
        send_as_document = self._should_send_generated_image_as_document(image_path)
        status_text = "✅ 图片已生成，正在发送原图文件……" if send_as_document else "✅ 图片已生成，正在发送图片……"
        await safe_edit_message(message, status_text, parse_mode="html")

        reply_to = getattr(replied_message, "id", None) if replied_message is not None else None
        await event.client.send_file(
            getattr(message, "chat_id", getattr(event, "chat_id", None)),
            file=str(image_path),
            caption=caption,
            parse_mode="html",
            force_document=send_as_document,
            reply_to=reply_to,
        )
        await safe_delete_message(message, "image_generation_cleanup")

    async def _handle_image_setting_command(self, message: Any) -> bool:
        text = _message_text(message)
        size = extract_prefixed_value(text, self.config.image.size_commands)
        if size is not None:
            if not size:
                await safe_edit_message(message, format_image_setting_message("尺寸", self.config.image.size), parse_mode="html")
                return True
            self.config.image.size = size
            self._save_image_settings()
            await safe_edit_message(message, format_image_setting_message("尺寸", self.config.image.size), parse_mode="html")
            return True

        mode = extract_prefixed_value(text, self.config.image.send_mode_commands)
        if mode is not None:
            if not mode:
                await safe_edit_message(message, format_image_setting_message("发送模式", self.config.image.send_mode), parse_mode="html")
                return True
            normalized = mode.strip().lower()
            if normalized not in {"auto", "always", "never"}:
                await safe_edit_message(message, "⚠️ 可选值：auto / always / never", parse_mode="html")
                return True
            self.config.image.send_mode = normalized
            self._save_image_settings()
            await safe_edit_message(message, format_image_setting_message("发送模式", self.config.image.send_mode), parse_mode="html")
            return True

        ratio = extract_prefixed_value(text, self.config.image.ratio_commands)
        if ratio is not None:
            if not ratio:
                await safe_edit_message(message, format_image_setting_message("画面比例", self.config.image.ratio), parse_mode="html")
                return True
            self.config.image.ratio = AUTO_IMAGE_RATIO if ratio.strip().lower() == AUTO_IMAGE_RATIO else ratio
            self._save_image_settings()
            await safe_edit_message(message, format_image_setting_message("画面比例", self.config.image.ratio), parse_mode="html")
            return True

        model = extract_prefixed_value(text, self.config.image.model_commands)
        if model is not None:
            if not model:
                await safe_edit_message(message, format_image_setting_message("模型", self.image_model), parse_mode="html")
                return True
            self.config.image_provider.model = model
            self._save_image_settings()
            await safe_edit_message(message, format_image_setting_message("模型", self.image_model), parse_mode="html")
            return True

        return False

    async def _collect_image_generation_context(self, message: Any, prompt: str, replied: Any) -> tuple[str, Path | None, str]:
        reference_text = ""
        reference_image_path: Path | None = None
        reference_note = ""

        if replied:
            reply_text = _message_text(replied)
            if reply_text:
                reference_text = reply_text[:MAX_CONTEXT_TEXT_CHARS]
                reference_note = "引用文字"
            if getattr(replied, "media", None):
                reference_image_path, media_note = await self._download_reference_image(replied)
                if reference_image_path:
                    reference_note = f"引用文字+{media_note}" if reference_text else media_note

        if not reference_image_path and getattr(message, "media", None):
            reference_image_path, media_note = await self._download_reference_image(message)
            if reference_image_path:
                reference_note = f"触发消息媒体:{media_note}"

        if reference_text:
            effective_prompt = (
                "请基于以下引用文字内容进行生图。\n"
                f"引用文字：\n{reference_text}\n\n"
                f"用户生图要求：\n{prompt or '请根据引用内容生成合适的图片。'}"
            )
        elif reference_image_path:
            effective_prompt = prompt or "请根据引用图片生成合适的图片。"
        else:
            effective_prompt = prompt or "请生成一张合适的图片。"
        return effective_prompt, reference_image_path, reference_note

    async def _download_reference_image(self, message: Any) -> tuple[Path | None, str]:
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            downloaded = await message.download_media(file=self.tmp_dir)
        except Exception as exc:
            logger.exception("Reference media download failed: %s", exc)
            return None, ""
        if not downloaded:
            return None, ""
        source_path = Path(downloaded)
        try:
            if media_is_tgs_sticker(message):
                logger.info("Skipped unsupported Telegram TGS sticker reference media: %s", source_path)
                _unlink_quietly(source_path)
                return None, ""
            if media_is_motion(message):
                frame = extract_first_frame_from_path_as_jpeg(source_path)
                if frame:
                    output_path = source_path.with_suffix(".jpg")
                    output_path.write_bytes(frame)
                    _unlink_quietly(source_path)
                    return output_path, "引用视频/动图关键帧"
            normalized = normalize_image_file_to_jpeg(source_path)
            return normalized, "引用图片/静态贴纸"
        except Exception as exc:
            logger.exception("Reference media conversion failed: %s", exc)
            _unlink_quietly(source_path)
            return None, ""

    def _generate_image_with_openai_compatible_api(self, prompt: str, output_path: Path, reference_image_path: Path | None = None) -> Path:
        api_key = self.image_api_key
        if not api_key:
            raise ImageProviderConfigError("作图功能未配置 image_provider.api_key 或 reply_provider.api_key。")
        if not self.image_model:
            raise ImageProviderConfigError("作图功能未配置 image_provider.model。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        xai_imagine = is_xai_imagine_provider(self.config.image_provider.provider_type)
        if xai_imagine:
            image_data_url = None
            if reference_image_path:
                mime_type = mimetypes.guess_type(str(reference_image_path))[0] or "image/jpeg"
                encoded_image = base64.b64encode(reference_image_path.read_bytes()).decode("ascii")
                image_data_url = f"data:{mime_type};base64,{encoded_image}"
            payload = build_xai_imagine_payload(
                model=self.image_model,
                prompt=prompt,
                size=self.config.image.size,
                ratio=self.config.image.ratio,
                quality=self.config.image.quality,
                image_data_url=image_data_url,
            )
            endpoint = "/images/edits" if reference_image_path else "/images/generations"
            url = self.image_base_url.rstrip("/") + endpoint
            request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
            api_size = f"{payload['resolution']}/{payload.get('aspect_ratio', 'source')}"
            feature = "image_generation_edit" if reference_image_path else "image_generation"
        elif reference_image_path:
            api_size = resolve_image_api_size(self.config.image.size, self.config.image.ratio)
            fields = {"model": self.image_model, "prompt": prompt, "size": api_size, "n": "1"}
            if self.config.image.quality:
                fields["quality"] = self.config.image.quality
            url = self.image_base_url.rstrip("/") + "/images/edits"
            mime_type = mimetypes.guess_type(str(reference_image_path))[0] or "image/jpeg"
            files = {"image": (reference_image_path.name, reference_image_path.read_bytes(), mime_type)}
            request_body, content_type = encode_multipart_formdata(fields, files)
            feature = "image_generation_edit"
        else:
            api_size = resolve_image_api_size(self.config.image.size, self.config.image.ratio)
            payload = {"model": self.image_model, "prompt": prompt, "size": api_size, "n": 1}
            if self.config.image.quality:
                payload["quality"] = self.config.image.quality
            url = self.image_base_url.rstrip("/") + "/images/generations"
            request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
            feature = "image_generation"

        logger.info(
            "AI image request started model=%s url=%s api_size=%s quality=%s prompt_len=%s reference=%s",
            self.image_model,
            url,
            api_size,
            self.config.image.quality,
            len(prompt),
            bool(reference_image_path),
        )
        started_at = time.monotonic()
        request = urllib.request.Request(
            ensure_http_url(url),
            data=request_body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.image.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
                self._record_ai_usage(feature, "images", self.image_model, True, started_at, data)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self._record_ai_usage(feature, "images", self.image_model, False, started_at, error=f"HTTP {exc.code} {body[:500]}")
            if not xai_imagine and not reference_image_path and should_fallback_to_responses_image_tool(body):
                logger.info("Images API failed on image_generation tool routing; trying Responses image_generation tool.")
                return self._generate_image_with_responses_tool(prompt, output_path)
            raise ImageProviderRequestError(format_image_provider_http_error(exc.code, xai_imagine=xai_imagine)) from exc
        except Exception as exc:
            self._record_ai_usage(feature, "images", self.image_model, False, started_at, error=str(exc))
            raise
        return save_image_api_result(
            data,
            output_path,
            self.config.image.timeout_seconds,
            api_key=api_key,
            api_base_url=self.image_base_url,
        )

    def _generate_image_with_responses_tool(self, prompt: str, output_path: Path) -> Path:
        api_key = self.image_api_key
        if not api_key:
            raise ValueError("Responses 生图未配置 API key。")
        api_size = resolve_image_api_size(self.config.image.size, self.config.image.ratio)
        model = self.config.reply_provider.model or self.image_model
        url = self.image_base_url.rstrip("/") + "/responses"
        payload = {
            "model": model,
            "input": prompt,
            "tools": [{"type": "image_generation", "size": api_size, "quality": self.config.image.quality}],
            "tool_choice": {"type": "image_generation"},
        }
        started_at = time.monotonic()
        request = urllib.request.Request(
            ensure_http_url(url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.image.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
                self._record_ai_usage("image_generation_responses_tool", "responses", model, True, started_at, data)
        except Exception as exc:
            self._record_ai_usage("image_generation_responses_tool", "responses", model, False, started_at, error=str(exc))
            raise
        return save_responses_image_result(data, output_path)

    def _reference_describe_prompt(self, edit_prompt: str) -> str:
        return (
            "请详细描述这张参考图，用于后续生图模型复刻或按用户要求修改。"
            "重点描述主体、构图、姿势、服装、画风、颜色、背景、光照、镜头和文字元素。"
            f"用户修改要求：{edit_prompt or '根据参考图生成合适图片'}"
        )

    def _call_ai_describe_reference_image(self, image_path: Path, edit_prompt: str) -> str:
        if is_anthropic_provider(self.config.reply_provider.provider_type):
            return self._describe_reference_with_anthropic(image_path, edit_prompt)
        api_key = self.config.reply_provider.api_key or self.image_api_key
        model = self.config.reply_provider.model
        base_url = (self.config.reply_provider.base_url or self.image_base_url).rstrip("/")
        if not api_key or not model:
            raise ValueError("参考图理解需要 reply_provider.api_key 和 reply_provider.model。")
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        data_url = "data:" + mime_type + ";base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._reference_describe_prompt(edit_prompt)},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.2,
            "max_tokens": 800,
        }
        started_at = time.monotonic()
        request = urllib.request.Request(
            ensure_http_url(base_url + "/chat/completions"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.reply.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
                self._record_ai_usage("reference_image_understanding", "chat_completions", model, True, started_at, data)
        except Exception as exc:
            self._record_ai_usage("reference_image_understanding", "chat_completions", model, False, started_at, error=str(exc))
            raise
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    def _describe_reference_with_anthropic(self, image_path: Path, edit_prompt: str) -> str:
        provider = self.config.reply_provider
        api_key = provider.api_key or self.image_api_key
        model = provider.model
        base_url = provider.base_url or self.image_base_url
        if not api_key or not model:
            raise ValueError("参考图理解需要 reply_provider.api_key 和 reply_provider.model。")
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": self._reference_describe_prompt(edit_prompt)},
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}},
        ]
        client = make_sync_anthropic_client(api_key, base_url, self.config.reply.timeout_seconds)
        started_at = time.monotonic()
        try:
            message = client.messages.create(
                model=model,
                max_tokens=800,
                messages=[{"role": "user", "content": content}],
            )
            self._record_ai_usage("reference_image_understanding", "messages", model, True, started_at, message)
        except Exception as exc:
            self._record_ai_usage("reference_image_understanding", "messages", model, False, started_at, error=str(exc))
            raise
        finally:
            try:
                client.close()
            except Exception:
                pass
        answer, _sources = collect_anthropic_text_and_sources(message)
        return answer

    def _should_send_generated_image_as_document(self, image_path: Path) -> bool:
        mode = (self.config.image.send_mode or "auto").lower()
        if image_exceeds_telegram_photo_limits(image_path):
            return True
        if mode == "always":
            return True
        if mode == "never":
            return False
        return self.config.image.size.strip().upper() == "4K"

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

    def _load_image_settings(self) -> None:
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load image settings store: %s", self.settings_path)
            return
        if data.get("size"):
            self.config.image.size = str(data["size"])
        if data.get("ratio"):
            self.config.image.ratio = str(data["ratio"])
        if data.get("model"):
            self.config.image_provider.model = str(data["model"])
        if data.get("send_mode") in {"auto", "always", "never"}:
            self.config.image.send_mode = str(data["send_mode"])

    def _save_image_settings(self) -> None:
        payload = {
            "size": self.config.image.size,
            "ratio": self.config.image.ratio,
            "model": self.image_model,
            "send_mode": self.config.image.send_mode,
        }
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.settings_path)
        self._sync_card_config()

    def _sync_card_config(self) -> None:
        self.card.config = {
            "provider": self.config.image_provider.name,
            "provider_type": self.config.image_provider.provider_type,
            "model": self.image_model,
            "base_url": self.image_base_url,
            "image": asdict(self.config.image),
            "settings_store": str(self.settings_path),
        }

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute() or self.project_root is None:
            return path
        return self.project_root / path

    @property
    def image_model(self) -> str:
        return self.config.image_provider.model

    @property
    def image_api_key(self) -> str:
        return self.config.image_provider.api_key or self.config.reply_provider.api_key

    @property
    def image_base_url(self) -> str:
        return self.config.image_provider.base_url or self.config.reply_provider.base_url or "https://api.openai.com/v1"


def extract_image_prompt(text: str, config: AIImageConfig) -> str | None:
    return extract_command_prompt(text, config.command_prefixes)


def extract_command_prompt(text: str, prefixes: list[str]) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    for prefix in sorted((item for item in prefixes if item), key=len, reverse=True):
        if stripped == prefix:
            return ""
        if stripped.startswith(prefix + " ") or stripped.startswith(prefix + "\n"):
            return stripped[len(prefix) :].strip()
    return None


def extract_prefixed_value(text: str, prefixes: list[str]) -> str | None:
    return extract_command_prompt(text, prefixes)


def format_image_setting_message(setting_name: str, value: str) -> str:
    return f"✅ 生图{html.escape(setting_name)}已设为： <b>{html.escape(value.strip() or '未提供')}</b>"


def format_image_status_message(prompt: str, status: str, model: str, ratio: str, size: str) -> str:
    safe_prompt = html.escape(prompt.strip() or "未提供提示词")
    safe_status = html.escape(status.strip())
    safe_model = html.escape(model.strip() or "未配置")
    safe_ratio = html.escape(ratio.strip() or "未配置")
    safe_size = html.escape(size.strip() or "未配置")
    return (
        "🎨 <b>Prompt</b>\n"
        f"<blockquote expandable>{safe_prompt}</blockquote>\n\n"
        "⏳ <b>Status</b>: "
        f"{safe_status}\n\n"
        f"📐 <b>Ratio</b>: <code>{safe_ratio}</code> | "
        f"🖼️ <b>Size</b>: <code>{safe_size}</code> | "
        f"🚀 <code>{safe_model}</code>"
    )


def format_image_caption(prompt: str, model: str, ratio: str, size: str) -> str:
    safe_prompt = html.escape(prompt.strip() or "未提供提示词")
    safe_model = html.escape(model.strip() or "unknown")
    safe_ratio = html.escape(ratio.strip() or "未配置")
    safe_size = html.escape(size.strip() or "未配置")
    return (
        "🎨 <b>Prompt</b>\n"
        f"<blockquote expandable>{safe_prompt}</blockquote>\n"
        f"📐 <b>Ratio</b>: <code>{safe_ratio}</code> | "
        f"🖼️ <b>Size</b>: <code>{safe_size}</code> | "
        f"🚀 <code>{safe_model}</code>"
    )


def round_to_multiple_of_16(value: float) -> int:
    return max(16, int(round(value / 16)) * 16)


def resolve_image_api_size(display_size: str, ratio: str) -> str:
    size = display_size.strip().upper()
    normalized_ratio = ratio.strip()
    if normalized_ratio.lower() == AUTO_IMAGE_RATIO:
        return AUTO_IMAGE_RATIO
    if re.fullmatch(r"\d+x\d+", size, re.IGNORECASE):
        return size.lower()
    ratio_values = {
        "1:1": (1, 1),
        "16:9": (16, 9),
        "9:16": (9, 16),
        "4:3": (4, 3),
        "3:4": (3, 4),
        "3:2": (3, 2),
        "2:3": (2, 3),
        "2:1": (2, 1),
        "1:2": (1, 2),
        "21:9": (21, 9),
        "9:21": (9, 21),
    }
    rw, rh = ratio_values.get(normalized_ratio, ratio_values["1:1"])
    if size == "1K":
        if rw == rh:
            width, height = 1024, 1024
        elif rw > rh:
            height = 1024
            width = round_to_multiple_of_16(height * rw / rh)
        else:
            width = 1024
            height = round_to_multiple_of_16(width * rh / rw)
    elif size == "2K":
        if rw >= rh:
            width = 2048
            height = round_to_multiple_of_16(width * rh / rw)
        else:
            height = 2048
            width = round_to_multiple_of_16(height * rw / rh)
    elif size == "4K":
        if rw == rh:
            width, height = 2880, 2880
        elif rw > rh:
            width = 3840
            height = round_to_multiple_of_16(width * rh / rw)
        else:
            height = 3840
            width = round_to_multiple_of_16(height * rw / rh)
    else:
        width, height = 1024, 1024
    while width * height > 8_294_400:
        width = max(16, width - 16)
        height = round_to_multiple_of_16(width * rh / rw)
    return f"{width}x{height}"


def encode_multipart_formdata(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----TgBotFormBoundary" + str(int(time.time() * 1000))
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, (filename, content, mime_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def is_xai_imagine_provider(provider_type: str) -> bool:
    return str(provider_type or "").strip().lower() in XAI_IMAGINE_PROVIDER_TYPES


def format_image_provider_http_error(status_code: int, *, xai_imagine: bool) -> str:
    provider_name = "xAI 上游" if xai_imagine else "图片服务"
    if status_code in {400, 422}:
        return f"{provider_name}拒绝了请求（HTTP {status_code}），可能是提示词触发内容审核，或模型不接受当前参数。"
    if status_code in {401, 403}:
        return f"{provider_name}鉴权失败（HTTP {status_code}），请检查 API Key、余额和模型权限。"
    if status_code == 429:
        return f"{provider_name}请求过于频繁或额度不足（HTTP 429），请稍后重试并检查余额。"
    if status_code >= 500:
        return f"{provider_name}暂时不可用（HTTP {status_code}），请稍后重试。"
    return f"{provider_name}请求失败（HTTP {status_code}）。"


def build_xai_imagine_payload(
    *,
    model: str,
    prompt: str,
    size: str,
    ratio: str,
    quality: str,
    image_data_url: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "resolution": resolve_xai_imagine_resolution(size),
    }
    if image_data_url:
        payload["image"] = {"type": "image_url", "url": image_data_url}
    else:
        payload["n"] = 1
        payload["aspect_ratio"] = resolve_xai_imagine_aspect_ratio(ratio)

    normalized_quality = str(quality or "").strip().lower()
    if model.strip().lower().startswith("grok-imagine-image-2.0") and normalized_quality in {"low", "medium"}:
        payload["quality"] = normalized_quality
    return payload


def resolve_xai_imagine_resolution(size: str) -> str:
    normalized = str(size or "").strip().lower()
    if normalized in {"1k", "2k"}:
        return normalized
    raise ImageProviderConfigError(f"xAI Imagine 仅支持 1K 或 2K 分辨率，当前配置为 {size or '空'}。")


def resolve_xai_imagine_aspect_ratio(ratio: str) -> str:
    normalized = str(ratio or AUTO_IMAGE_RATIO).strip().lower()
    if normalized in XAI_IMAGINE_ASPECT_RATIOS:
        return normalized
    allowed = ", ".join(sorted(XAI_IMAGINE_ASPECT_RATIOS))
    raise ImageProviderConfigError(f"xAI Imagine 不支持比例 {ratio or '空'}；可用值：{allowed}。")


def save_image_api_result(
    data: dict[str, Any],
    output_path: Path,
    timeout_seconds: float,
    *,
    api_key: str = "",
    api_base_url: str = "",
) -> Path:
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"图片 API 返回格式异常：{data}") from exc
    if item.get("b64_json"):
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
        return output_path
    image_url = item.get("url")
    if image_url:
        safe_image_url = ensure_http_url(image_url)
        image_request = urllib.request.Request(safe_image_url, headers=IMAGE_DOWNLOAD_HEADERS)
        if api_key and same_http_origin(safe_image_url, api_base_url):
            # Keep the credential out of redirected requests so a provider cannot
            # forward it to a different image/CDN origin.
            image_request.add_unredirected_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(image_request, timeout=timeout_seconds) as response:
            output_path.write_bytes(response.read())
        return output_path
    raise RuntimeError(f"图片 API 未返回 b64_json 或 url：{data}")


def same_http_origin(first_url: str, second_url: str) -> bool:
    try:
        first = urllib.parse.urlsplit(first_url)
        second = urllib.parse.urlsplit(second_url)
        if first.scheme.lower() not in {"http", "https"} or second.scheme.lower() not in {"http", "https"}:
            return False
        first_port = first.port or (443 if first.scheme.lower() == "https" else 80)
        second_port = second.port or (443 if second.scheme.lower() == "https" else 80)
    except ValueError:
        return False
    return (
        first.scheme.lower() == second.scheme.lower()
        and (first.hostname or "").lower() == (second.hostname or "").lower()
        and first_port == second_port
    )


def save_responses_image_result(data: dict[str, Any], output_path: Path) -> Path:
    for item in data.get("output", []) or []:
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type != "image_generation_call":
            continue
        result = item.get("result") if isinstance(item, dict) else getattr(item, "result", None)
        if result:
            output_path.write_bytes(base64.b64decode(result))
            return output_path
    raise RuntimeError(f"Responses API 未返回 image_generation_call.result：{str(data)[:1000]}")


def should_fallback_to_responses_image_tool(error_body: str) -> bool:
    lowered = error_body.lower()
    return "tool choice 'image_generation'" in lowered or ("image_generation" in lowered and "tools" in lowered)


def normalize_image_file_to_jpeg(image_path: Path) -> Path:
    if Image is None:
        return image_path
    with Image.open(image_path) as img:
        img.load()
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            alpha = img.convert("RGBA").split()[3]
            background.paste(img.convert("RGBA"), mask=alpha)
        else:
            background = img.convert("RGB")
        output_path = image_path.with_suffix(".jpg")
        background.save(output_path, format="JPEG", quality=90)
    if output_path != image_path:
        _unlink_quietly(image_path)
    return output_path


def image_exceeds_telegram_photo_limits(image_path: Path) -> bool:
    if image_path.stat().st_size > TELEGRAM_PHOTO_SIZE_LIMIT:
        return True
    if Image is None:
        return False
    try:
        with Image.open(image_path) as img:
            width, height = img.size
        return (width + height) > 10000 or (max(width, height) / max(1, min(width, height))) > 20
    except Exception:
        logger.exception("Failed to read generated image dimensions; sending as photo by default.")
        return False


def is_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() or "timeout" in exc.__class__.__name__.lower()


async def _get_reply_message(message: Any) -> Any:
    if message is None or not getattr(message, "is_reply", False) or not hasattr(message, "get_reply_message"):
        return None
    try:
        return await message.get_reply_message()
    except Exception:
        logger.exception("Failed to load replied message")
        return None


def _event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def _message_text(message: Any) -> str:
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, "")
        if isinstance(value, str):
            return value.strip()
    return ""


def _is_outgoing(event: Any) -> bool:
    message = _event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


def _unlink_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _image_config_from_dict(data: dict[str, Any]) -> AIImageConfig:
    return AIImageConfig(
        command_prefixes=_clean_list(data.get("command_prefixes")),
        size=str(data.get("size") or "1K"),
        ratio=str(data.get("ratio") or "1:1"),
        quality=str(data.get("quality") or "standard"),
        send_mode=str(data.get("send_mode") or "auto"),
        timeout_seconds=float(data.get("timeout_seconds") or 120.0),
        output_dir=str(data.get("output_dir") or "runtime/data/generated_images"),
        settings_store=str(data.get("settings_store") or "runtime/data/image_settings.json"),
        size_commands=_clean_list(data.get("size_commands")),
        ratio_commands=_clean_list(data.get("ratio_commands")),
        send_mode_commands=_clean_list(data.get("send_mode_commands")),
        model_commands=_clean_list(data.get("model_commands")),
    )


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
