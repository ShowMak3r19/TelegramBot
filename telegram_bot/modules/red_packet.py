from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from telegram_bot.config import RedPacketConfig, RedPacketTemplateConfig
from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard

logger = logging.getLogger(__name__)
CLAIM_TTL_SECONDS = 48 * 60 * 60


class RedPacketModule:
    def __init__(
        self,
        card: ModuleCard,
        config: RedPacketConfig,
        claimed_ids_path: Path | None = None,
        now_func: Any = time.time,
        choice_func: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.card = card
        self.config = config
        self.claimed_ids_path = claimed_ids_path
        self.now_func = now_func
        self.choice_func = choice_func if choice_func is not None else random.choice
        self.claimed_ids = self._load_claimed_ids()
        self._claim_lock = asyncio.Lock()
        self._inflight_claims: set[tuple[str, str]] = set()
        self._sync_card_config()

    async def start(self) -> None:
        self.cleanup_claimed_ids()
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, message: Any) -> HandlerResult:
        if _is_outgoing(message):
            return HandlerResult.ignored(self.card.id)

        text = _message_text(message)
        if not text:
            return HandlerResult.ignored(self.card.id)

        button_result = await self._handle_click_button(message, text)
        if button_result is not None:
            return button_result

        template = self.match_template(text)
        if template is None:
            return HandlerResult.ignored(self.card.id)

        red_packet_id = self.extract_red_packet_id(text, template)
        if not red_packet_id:
            logger.warning("Red packet template matched but no red packet id was extracted: %s", template.id)
            return HandlerResult.failed(self.card.id, "matched template but no red packet id was extracted")
        if self._is_claimed(template.id, red_packet_id):
            logger.info("Red packet already claimed: template=%s id=%s", template.id, red_packet_id)
            return HandlerResult.ignored(self.card.id)

        passphrase = self.extract_passphrase(text, template)
        if not passphrase:
            logger.warning("Red packet template matched but no passphrase was extracted: %s", template.id)
            return HandlerResult.failed(self.card.id, "matched template but no passphrase was extracted")

        self._mark_claimed(template.id, red_packet_id)
        if hasattr(message, "respond"):
            delay_seconds = max(0, int(self.config.send_delay_ms or 0)) / 1000
            if delay_seconds:
                logger.info("Red packet send delayed: template=%s id=%s delay_ms=%s", template.id, red_packet_id, self.config.send_delay_ms)
                await asyncio.sleep(delay_seconds)
            await message.respond(passphrase)
        logger.info("Red packet template matched: %s", template.name or template.id)
        return HandlerResult.handled(
            self.card.id,
            "red packet passphrase sent",
            {
                "template_id": template.id,
                "template_name": template.name,
                "red_packet_id": red_packet_id,
                "passphrase": passphrase,
            },
        )

    async def _handle_click_button(self, message: Any, text: str) -> HandlerResult | None:
        template = self.match_button_template(text, message)
        if template is None:
            return None

        red_packet_id = self.extract_red_packet_id(text, template) or _message_claim_key(message)
        if not red_packet_id:
            logger.warning("Red packet button template matched but no stable id was available: %s", template.id)
            return HandlerResult.failed(self.card.id, "matched button template but no stable id was available")

        target_text = _matching_button_text(message, template.button_texts)
        if not target_text:
            logger.warning("Red packet button template matched but target button was missing: %s", template.id)
            return HandlerResult.failed(self.card.id, "matched button template but target button was missing")

        # Snapshot all mutable configuration before the first await. Admin updates run
        # on a separate HTTP thread, so a single claim must use one coherent view.
        template_id = template.id
        template_name = template.name
        send_message_before_click = bool(template.send_message_before_click)
        delay_before_click = bool(template.delay_before_click)
        pre_click_messages = tuple(_clean_list(self.config.pre_click_messages))
        send_delay_ms = max(0, min(int(self.config.send_delay_ms or 0), 60_000))
        claim_key = (template_id, red_packet_id)

        async with self._claim_lock:
            if self._is_claimed(template_id, red_packet_id) or claim_key in self._inflight_claims:
                logger.info("Red packet button already clicked or in progress: template=%s id=%s", template_id, red_packet_id)
                return HandlerResult.ignored(self.card.id)
            self._inflight_claims.add(claim_key)

        try:
            initial_click_error = ""
            try:
                initial_callback_result = await _click_message_button(message, target_text)
            except Exception as exc:
                initial_click_error = _bounded_log_value(str(exc))
                logger.warning(
                    "Red packet button click failed: phase=initial template=%s id=%s button=%s error=%s",
                    template_id,
                    red_packet_id,
                    target_text,
                    exc,
                )
                return HandlerResult(
                    status="failed",
                    module_id=self.card.id,
                    message=f"red packet button click failed: {exc}",
                    metadata=_button_click_metadata(
                        template_id=template_id,
                        template_name=template_name,
                        red_packet_id=red_packet_id,
                        button_text=target_text,
                        initial_result=None,
                        initial_click_error=initial_click_error,
                    ),
                )

            initial_outcome = _classify_callback_result(initial_callback_result)
            _log_callback_result(
                phase="initial",
                outcome=initial_outcome,
                template_id=template_id,
                red_packet_id=red_packet_id,
                button_text=target_text,
                result=initial_callback_result,
            )
            initial_metadata = _button_click_metadata(
                template_id=template_id,
                template_name=template_name,
                red_packet_id=red_packet_id,
                button_text=target_text,
                initial_result=initial_callback_result,
            )

            if initial_outcome in {"success", "ended", "unknown"}:
                async with self._claim_lock:
                    self._mark_claimed(template_id, red_packet_id)
                return HandlerResult.handled(
                    self.card.id,
                    _callback_outcome_message(initial_outcome, phase="initial"),
                    initial_metadata,
                )

            if not send_message_before_click:
                async with self._claim_lock:
                    self._mark_claimed(template_id, red_packet_id)
                return HandlerResult.handled(
                    self.card.id,
                    "red packet eligibility restriction",
                    initial_metadata,
                )

            if not pre_click_messages:
                logger.warning("Red packet pre-click messages are empty: template=%s id=%s", template_id, red_packet_id)
                return HandlerResult(
                    status="failed",
                    module_id=self.card.id,
                    message="red packet pre-click messages are empty",
                    metadata=initial_metadata,
                )

            source_message = _event_message(message)
            respond = getattr(source_message, "respond", None)
            if not callable(respond):
                logger.warning("Red packet message cannot respond before retry: template=%s id=%s", template_id, red_packet_id)
                return HandlerResult(
                    status="failed",
                    module_id=self.card.id,
                    message="red packet message does not expose a respond API",
                    metadata=initial_metadata,
                )

            try:
                selected_message = str(self.choice_func(list(pre_click_messages))).strip()
                if not selected_message:
                    logger.warning("Red packet pre-click message selection was empty: template=%s id=%s", template_id, red_packet_id)
                    return HandlerResult(
                        status="failed",
                        module_id=self.card.id,
                        message="red packet pre-click messages are empty",
                        metadata=initial_metadata,
                    )
                await respond(selected_message)
            except Exception as exc:
                logger.warning("Red packet pre-click message failed: template=%s id=%s error=%s", template_id, red_packet_id, exc)
                return HandlerResult(
                    status="failed",
                    module_id=self.card.id,
                    message=f"red packet pre-click message failed: {exc}",
                    metadata=initial_metadata,
                )

            logger.info("Red packet message sent before retry: template=%s id=%s", template_id, red_packet_id)

            if delay_before_click and send_delay_ms:
                logger.info("Red packet retry click delayed: template=%s id=%s delay_ms=%s", template_id, red_packet_id, send_delay_ms)
                await asyncio.sleep(send_delay_ms / 1000)

            try:
                callback_result = await _click_message_button(message, target_text)
            except Exception as exc:
                retry_click_error = _bounded_log_value(str(exc))
                logger.warning(
                    "Red packet button click failed: phase=retry template=%s id=%s button=%s "
                    "initial_outcome=%s error=%s",
                    template_id,
                    red_packet_id,
                    target_text,
                    initial_outcome,
                    exc,
                )
                return HandlerResult(
                    status="failed",
                    module_id=self.card.id,
                    message=f"red packet button click failed: {exc}",
                    metadata=_button_click_metadata(
                        template_id=template_id,
                        template_name=template_name,
                        red_packet_id=red_packet_id,
                        button_text=target_text,
                        initial_result=initial_callback_result,
                        retry_result=None,
                        retry_performed=True,
                        retry_click_error=retry_click_error,
                    ),
                )

            retry_outcome = _classify_callback_result(callback_result)
            _log_callback_result(
                phase="retry",
                outcome=retry_outcome,
                template_id=template_id,
                red_packet_id=red_packet_id,
                button_text=target_text,
                result=callback_result,
            )
            async with self._claim_lock:
                self._mark_claimed(template_id, red_packet_id)

            return HandlerResult.handled(
                self.card.id,
                _callback_outcome_message(retry_outcome, phase="retry"),
                _button_click_metadata(
                    template_id=template_id,
                    template_name=template_name,
                    red_packet_id=red_packet_id,
                    button_text=target_text,
                    initial_result=initial_callback_result,
                    retry_result=callback_result,
                    retry_performed=True,
                ),
            )
        finally:
            async with self._claim_lock:
                self._inflight_claims.discard(claim_key)

    def match_template(self, text: str) -> RedPacketTemplateConfig | None:
        normalized = text.casefold()
        for template in self.config.templates:
            if not template.enabled:
                continue
            if not template.passphrase_markers and not template.passphrase.strip():
                continue
            if not _matches_any(normalized, template.trigger_keywords):
                continue
            if template.id_markers and not self.extract_red_packet_id(text, template):
                continue
            if not self.extract_passphrase(text, template):
                continue
            return template
        return None

    def match_button_template(self, text: str, message: Any) -> RedPacketTemplateConfig | None:
        normalized = text.casefold()
        for template in self.config.templates:
            if not template.enabled or not template.button_texts:
                continue
            if not _matches_any(normalized, template.trigger_keywords):
                continue
            if not _matching_button_text(message, template.button_texts):
                continue
            return template
        return None

    def extract_red_packet_id(self, text: str, template: RedPacketTemplateConfig) -> str:
        for marker in template.id_markers:
            red_packet_id = _extract_after_marker(text, marker)
            if red_packet_id:
                return _first_token(red_packet_id)
            if marker.casefold() in text.casefold():
                return marker.strip()
        return ""

    def extract_passphrase(self, text: str, template: RedPacketTemplateConfig) -> str:
        if template.passphrase_markers:
            for marker in template.passphrase_markers:
                passphrase = _extract_after_marker(text, marker)
                if _is_safe_passphrase(passphrase):
                    return passphrase
            return ""
        passphrase = template.passphrase.strip()
        return passphrase if _is_safe_passphrase(passphrase) else ""

    def update_config(self, values: dict[str, Any]) -> None:
        templates = values.get("templates")
        if isinstance(templates, list):
            self.config.templates = [
                _template_from_dict(item)
                for item in templates
                if isinstance(item, dict)
            ]
        if "send_delay_ms" in values:
            self.config.send_delay_ms = max(0, min(int(values.get("send_delay_ms") or 0), 60_000))
        if "pre_click_messages" in values:
            self.config.pre_click_messages = _clean_list(values.get("pre_click_messages"))
        self._sync_card_config()
        logger.info(
            "Red packet config updated: %s active delay_ms=%s pre_click_messages=%s",
            self._enabled_template_count(),
            self.config.send_delay_ms,
            len(self.config.pre_click_messages),
        )

    def cleanup_claimed_ids(self) -> None:
        now = self.now_func()
        changed = False
        for template_id in list(self.claimed_ids.keys()):
            entries = self.claimed_ids.get(template_id, {})
            if not isinstance(entries, dict):
                self.claimed_ids[template_id] = {}
                changed = True
                continue
            fresh = {
                red_packet_id: claimed_at
                for red_packet_id, claimed_at in entries.items()
                if _is_fresh_claim(claimed_at, now)
            }
            if fresh != entries:
                self.claimed_ids[template_id] = fresh
                changed = True
        if changed:
            self._save_claimed_ids()

    def _sync_card_config(self) -> None:
        self.card.config = {
            "templates": [asdict(template) for template in self.config.templates],
            "template_count": len(self.config.templates),
            "enabled_template_count": self._enabled_template_count(),
            "match_strategy": "template",
            "image_recognition": False,
            "button_click": True,
            "claimed_id_ttl_hours": 48,
            "send_delay_ms": self.config.send_delay_ms,
            "pre_click_messages": list(self.config.pre_click_messages),
        }

    def _enabled_template_count(self) -> int:
        return sum(1 for template in self.config.templates if template.enabled)

    def _is_claimed(self, template_id: str, red_packet_id: str) -> bool:
        self.cleanup_claimed_ids()
        entries = self.claimed_ids.get(template_id, {})
        claimed_at = entries.get(red_packet_id)
        return _is_fresh_claim(claimed_at, self.now_func())

    def _mark_claimed(self, template_id: str, red_packet_id: str) -> None:
        self.cleanup_claimed_ids()
        self.claimed_ids.setdefault(template_id, {})[red_packet_id] = self.now_func()
        self._save_claimed_ids()

    def _load_claimed_ids(self) -> dict[str, dict[str, float]]:
        if self.claimed_ids_path is None or not self.claimed_ids_path.exists():
            return {}
        try:
            with self.claimed_ids_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load red packet claimed ids, starting empty")
            return {}
        templates = data.get("templates", {}) if isinstance(data, dict) else {}
        if not isinstance(templates, dict):
            return {}
        loaded: dict[str, dict[str, float]] = {}
        for template_id, entries in templates.items():
            if not isinstance(entries, dict):
                continue
            loaded[str(template_id)] = {
                str(red_packet_id): float(claimed_at)
                for red_packet_id, claimed_at in entries.items()
                if _as_float(claimed_at) is not None
            }
        return loaded

    def _save_claimed_ids(self) -> None:
        if self.claimed_ids_path is None:
            return
        self.claimed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "ttl_seconds": CLAIM_TTL_SECONDS,
            "templates": self.claimed_ids,
        }
        self.claimed_ids_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _template_from_dict(data: dict[str, Any]) -> RedPacketTemplateConfig:
    return RedPacketTemplateConfig(
        id=str(data.get("id") or "").strip(),
        name=str(data.get("name") or "").strip(),
        enabled=bool(data.get("enabled", True)),
        trigger_keywords=_clean_list(data.get("trigger_keywords")),
        id_markers=_clean_list(data.get("id_markers")),
        passphrase_markers=_clean_list(data.get("passphrase_markers")),
        button_texts=_clean_list(data.get("button_texts")),
        passphrase=str(data.get("passphrase") or "").strip(),
        send_message_before_click=bool(data.get("send_message_before_click", False)),
        delay_before_click=bool(data.get("delay_before_click", True)),
    )


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _message_text(message: Any) -> str:
    message = _event_message(message)
    for attr in ("raw_text", "text", "message"):
        value = getattr(message, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _matches_any(text: str, values: list[str]) -> bool:
    cleaned = [value.casefold().strip() for value in values if value.strip()]
    if not cleaned:
        return True
    return any(value in text for value in cleaned)


def _is_fresh_claim(value: Any, now: float) -> bool:
    claimed_at = _as_float(value)
    return claimed_at is not None and now - claimed_at < CLAIM_TTL_SECONDS


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_after_marker(text: str, marker: str) -> str:
    marker = marker.strip()
    if not marker:
        return ""
    lines = text.splitlines()
    marker_folded = marker.casefold()
    for index, line in enumerate(lines):
        position = line.casefold().find(marker_folded)
        if position < 0:
            continue
        after = line[position + len(marker) :].strip()
        after = _strip_prefix_punctuation(after)
        if after:
            return _bounded_value(after)
        for following in lines[index + 1 :]:
            candidate = following.strip()
            if candidate:
                return _bounded_value(candidate)
    return ""


def _strip_prefix_punctuation(value: str) -> str:
    return value.lstrip(" \t:：-—|｜")


def _first_token(value: str) -> str:
    return value.strip().split()[0] if value.strip() else ""


def _bounded_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    quoted = _extract_quoted(value)
    return quoted or value


def _extract_quoted(value: str) -> str:
    pairs = [("「", "」"), ("“", "”"), ("\"", "\""), ("'", "'")]
    for left, right in pairs:
        start = value.find(left)
        if start < 0:
            continue
        end = value.find(right, start + len(left))
        if end > start:
            return value[start + len(left) : end].strip()
    return ""


def _is_safe_passphrase(value: str) -> bool:
    return bool(value.strip()) and not value.lstrip().startswith("/")


def _event_message(event: Any) -> Any:
    return getattr(event, "message", event)


def _is_outgoing(event: Any) -> bool:
    message = _event_message(event)
    return bool(getattr(message, "out", getattr(event, "out", False)))


def _matching_button_text(event: Any, button_texts: list[str]) -> str:
    configured = [item.casefold().strip() for item in button_texts if item.strip()]
    if not configured:
        return ""
    for button_text in _message_button_texts(event):
        normalized = button_text.casefold().strip()
        if any(item == normalized or item in normalized for item in configured):
            return button_text
    return ""


def _message_button_texts(event: Any) -> list[str]:
    message = _event_message(event)
    buttons = getattr(message, "buttons", None)
    if not buttons:
        return []
    texts: list[str] = []
    for row in buttons:
        row_buttons = row if isinstance(row, (list, tuple)) else [row]
        for button in row_buttons:
            text = getattr(button, "text", None)
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return texts


async def _click_message_button(event: Any, button_text: str) -> Any:
    message = _event_message(event)
    click = getattr(message, "click", None) or getattr(event, "click", None)
    if not callable(click):
        raise RuntimeError("message does not expose a clickable button API")
    result = click(text=button_text)
    if hasattr(result, "__await__"):
        return await result
    return result


def _classify_callback_result(result: Any) -> str:
    message, _, url = _callback_result_fields(result)
    if url:
        return "unknown"

    compact = "".join(message.split()).rstrip("。.!！")
    if not compact:
        return "unknown"

    success_prefix = "你抢到了"
    success_suffix = "银元"
    if compact.startswith(success_prefix) and compact.endswith(success_suffix):
        amount = compact[len(success_prefix) : -len(success_suffix)].replace(",", "").replace("，", "")
        if amount.isdigit():
            return "success"
    if re.fullmatch(r"红包前\d+秒仅限最近\d+位发言人领取", compact):
        return "eligibility"
    terminal_markers = (
        "这个红包已经结束",
        "红包已经结束",
        "红包已结束",
        "红包已经抢完",
        "红包已抢完",
        "红包已经领完",
        "红包已领完",
        "已领完",
        "每人只能领取一次",
        "你已经领取过",
    )
    if any(marker in compact for marker in terminal_markers):
        return "ended"
    return "unknown"


def _callback_outcome_message(outcome: str, *, phase: str) -> str:
    if outcome == "success":
        return "red packet claimed"
    if outcome == "ended":
        return "red packet ended"
    if outcome == "eligibility":
        if phase == "retry":
            return "red packet still ineligible after retry"
        return "red packet eligibility restriction"
    return "red packet callback unrecognized"


def _callback_result_fields(result: Any) -> tuple[str, bool | None, str]:
    message_value = getattr(result, "message", None)
    if isinstance(message_value, str):
        message = message_value.strip()
    elif isinstance(result, str) and not result.strip().casefold().startswith(("http://", "https://", "tg://")):
        message = result.strip()
    else:
        message = ""

    alert_value = getattr(result, "alert", None)
    alert = alert_value if isinstance(alert_value, bool) else None

    url_value = getattr(result, "url", None)
    if isinstance(url_value, str):
        url = url_value.strip()
    elif isinstance(result, str) and result.strip().casefold().startswith(("http://", "https://", "tg://")):
        url = result.strip()
    else:
        url = ""
    return message, alert, url


def _log_callback_result(
    *,
    phase: str,
    outcome: str,
    template_id: str,
    red_packet_id: str,
    button_text: str,
    result: Any,
) -> None:
    message, alert, url = _callback_result_fields(result)
    log_callback = logger.warning if outcome == "unknown" else logger.info
    log_callback(
        "Red packet callback received: phase=%s outcome=%s template=%s id=%s button=%s "
        "message=%s alert=%s url=%s callback=%s",
        phase,
        outcome,
        template_id,
        red_packet_id,
        button_text,
        _bounded_log_value(message) or "[empty]",
        alert,
        _bounded_log_value(url) or "[empty]",
        _callback_result_text(result) or "[empty]",
    )


def _button_click_metadata(
    *,
    template_id: str,
    template_name: str,
    red_packet_id: str,
    button_text: str,
    initial_result: Any,
    retry_result: Any = None,
    retry_performed: bool = False,
    initial_click_error: str = "",
    retry_click_error: str = "",
) -> dict[str, Any]:
    initial_message, initial_alert, initial_url = _callback_result_fields(initial_result)
    initial_message = _bounded_log_value(initial_message)
    initial_url = _bounded_log_value(initial_url)
    initial_callback = _callback_result_text(initial_result)
    initial_outcome = "" if initial_click_error else _classify_callback_result(initial_result)

    if retry_performed:
        if retry_click_error:
            retry_message = ""
            retry_alert = None
            retry_url = ""
            retry_callback = ""
            retry_outcome = ""
            final_message = initial_message
            final_alert = initial_alert
            final_url = initial_url
            final_callback = initial_callback
            final_outcome = initial_outcome
        else:
            retry_message, retry_alert, retry_url = _callback_result_fields(retry_result)
            retry_message = _bounded_log_value(retry_message)
            retry_url = _bounded_log_value(retry_url)
            retry_callback = _callback_result_text(retry_result)
            retry_outcome = _classify_callback_result(retry_result)
            final_message = retry_message
            final_alert = retry_alert
            final_url = retry_url
            final_callback = retry_callback
            final_outcome = retry_outcome
    else:
        retry_message = ""
        retry_alert = None
        retry_url = ""
        retry_callback = ""
        retry_outcome = ""
        final_message = initial_message
        final_alert = initial_alert
        final_url = initial_url
        final_callback = initial_callback
        final_outcome = initial_outcome

    return {
        "template_id": template_id,
        "template_name": template_name,
        "red_packet_id": red_packet_id,
        "button_text": button_text,
        "outcome": final_outcome,
        "callback": final_callback,
        "callback_message": final_message,
        "callback_alert": final_alert,
        "callback_url": final_url,
        "initial_outcome": initial_outcome,
        "initial_callback": initial_callback,
        "initial_callback_message": initial_message,
        "initial_callback_alert": initial_alert,
        "initial_callback_url": initial_url,
        "initial_click_error": initial_click_error,
        "retry_outcome": retry_outcome,
        "retry_callback": retry_callback,
        "retry_callback_message": retry_message,
        "retry_callback_alert": retry_alert,
        "retry_callback_url": retry_url,
        "retry_click_error": retry_click_error,
    }


def _callback_result_text(result: Any) -> str:
    if result is None:
        return ""
    parts: list[str] = []
    for attr in ("message", "alert", "url"):
        value = getattr(result, attr, None)
        if value is None or value == "":
            continue
        parts.append(f"{attr}={value}")
    if parts:
        return _bounded_log_value(" ".join(parts))
    return _bounded_log_value(str(result))


def _bounded_log_value(value: str, limit: int = 240) -> str:
    value = " ".join(value.split())
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _message_claim_key(event: Any) -> str:
    message = _event_message(event)
    chat_id = getattr(event, "chat_id", getattr(message, "chat_id", ""))
    message_id = getattr(message, "id", getattr(event, "id", ""))
    if chat_id or message_id:
        return f"message:{chat_id}:{message_id}"
    text = _message_text(message)
    return f"text:{hashlib.sha256(text.encode('utf-8')).hexdigest()}" if text else ""
