from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .admin import AdminServer
from .config import AIProviderConfig, AppConfig
from .jobs import ChatHistoryBackfillJob
from .logging_setup import RecentLogBuffer, configure_logging
from .modules import ModuleRegistry, create_default_registry
from .persistence import ChatHistoryStore
from .runtime import RuntimeMetrics, ensure_runtime_dirs, system_snapshot
from .telegram import TelegramAdapter
from .usage import build_ai_usage_stats

logger = logging.getLogger(__name__)


class TelegramBotApplication:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.project_root = Path(__file__).resolve().parents[1]
        self.metrics = RuntimeMetrics()
        self.chat_history = ChatHistoryStore(config.chat_history, self.project_root)
        self.modules: ModuleRegistry = create_default_registry(config, self.project_root, self.chat_history)
        self.recent_logs: RecentLogBuffer = RecentLogBuffer()
        self.telegram = TelegramAdapter(config.telegram, self.project_root, self._on_telegram_message)
        self.chat_history_backfill = ChatHistoryBackfillJob(
            config.chat_history,
            config.telegram,
            self.telegram,
            self.chat_history,
        )
        checkin = self.modules.get("checkin")
        if checkin is not None and hasattr(checkin, "set_sender"):
            checkin.set_sender(self.telegram.send_message)
        self.admin = AdminServer(self)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.service_state = "starting"
        self.dashboard_history: list[dict[str, float]] = []

    async def run_forever(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._install_signal_handlers()
        ensure_runtime_dirs(
            self.project_root,
            [
                self.config.runtime.data_dir,
                self.config.runtime.tmp_dir,
                self.config.telegram.session_dir,
                self.config.logs.dir,
            ],
        )
        self.recent_logs = configure_logging(self.config.logs, self.project_root)
        logger.info("Starting %s %s", self.config.project_name, self.config.version)
        self.admin.start()
        await self.start_service()
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        await stop_event.wait()

    async def start_service(self) -> None:
        self.service_state = "starting"
        await self.telegram.start()
        await self.chat_history_backfill.start()
        await self.modules.start_enabled()
        self.service_state = "running"
        logger.info("Core service started")

    async def stop_service(self) -> None:
        self.service_state = "stopping"
        await self.chat_history_backfill.stop()
        await self.modules.stop_all()
        await self.telegram.stop()
        self.service_state = "stopped"
        logger.info("Core service stopped")

    async def restart_service(self) -> None:
        await self.stop_service()
        argv = [sys.executable, "-m", "telegram_bot", "--config", str(self.config_path)]
        logger.warning("Replacing the Python process for a full service restart")
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        try:
            os.execv(sys.executable, argv)
        except OSError:
            logger.exception("Full service restart failed; restoring the stopped service")
            await self.start_service()
            raise

    async def shutdown(self) -> None:
        await self.stop_service()
        self.chat_history.close()
        self.admin.stop()
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    def request_service_action(self, action: str) -> None:
        if not self.loop:
            return
        mapping = {
            "start": self.start_service,
            "stop": self.stop_service,
            "restart": self.restart_service,
        }
        func = mapping[action]
        asyncio.run_coroutine_threadsafe(func(), self.loop)

    async def _on_telegram_message(self, event: Any) -> None:
        self.metrics.messages_seen += 1
        try:
            await asyncio.to_thread(self.chat_history.record_event, event)
        except Exception:
            logger.exception("Failed to archive monitored Telegram message text")
        try:
            results = await self.modules.dispatch_message(event)
            if results:
                logger.info(
                    "Telegram message module results: %s",
                    ", ".join(f"{result.module_id}={result.status}" for result in results),
                )
            else:
                logger.info("Telegram message matched no enabled module")
            if any(result.status == "handled" for result in results):
                self.metrics.messages_handled += 1
        except Exception:
            self.metrics.failures += 1
            logger.exception("Telegram message dispatch failed")

    def status_snapshot(self) -> dict[str, Any]:
        metrics = self.metrics.snapshot()
        system = system_snapshot(self.project_root, metrics["uptime_seconds"])
        self._record_dashboard_sample(metrics, system)
        return {
            "project": {
                "name": self.config.project_name,
                "version": self.config.version,
                "config_path": str(self.config_path),
                "root": str(self.project_root),
            },
            "service": {"state": self.service_state},
            "telegram": self.telegram.status(),
            "chat_history_backfill": self.chat_history_backfill.status(),
            "metrics": metrics,
            "system": system,
            "history": self.dashboard_history,
            "modules": self.modules.cards(),
            "logs": {
                "dir": self.config.logs.dir,
                "file_name": self.config.logs.file_name,
                "max_bytes": self.config.logs.max_bytes,
                "max_files": self.config.logs.max_files,
            },
        }

    def _record_dashboard_sample(self, metrics: dict[str, Any], system: dict[str, Any]) -> None:
        stats = system.get("stats", {})
        sample = {
            "ts": time.time(),
            "cpu": float(metrics.get("cpu_percent") or 0),
            "memory": float(stats.get("memory_percent") or 0),
            "upload_bytes": float(stats.get("upload_bytes") or 0),
            "download_bytes": float(stats.get("download_bytes") or 0),
        }
        self.dashboard_history.append(sample)
        if len(self.dashboard_history) > 720:
            del self.dashboard_history[:-720]

    def ai_snapshot(self) -> dict[str, Any]:
        self._sync_runtime_ai_settings_from_modules()
        return {
            "providers": {
                "reply": self._public_ai_provider(self.config.ai.reply_provider),
                "image": self._public_ai_provider(self.config.ai.image_provider),
            },
            "reply": asdict(self.config.ai.reply),
            "image": asdict(self.config.ai.image),
        }

    def ai_usage_snapshot(self, range_key: str = "today") -> dict[str, Any]:
        data_dir = Path(self.config.runtime.data_dir)
        if not data_dir.is_absolute():
            data_dir = self.project_root / data_dir
        return build_ai_usage_stats(data_dir / "ai_usage.jsonl", range_key)

    def update_ai_config(self, values: dict[str, Any]) -> dict[str, Any]:
        ai = values.get("ai", values)
        if not isinstance(ai, dict):
            return self.ai_snapshot()

        previous_enabled = {
            module_id: bool(module.card.enabled)
            for module_id in ("ai_reply", "ai_image", "ai_decrypt")
            if (module := self.modules.get(module_id)) is not None
        }
        self._sync_runtime_ai_settings_from_modules()
        self._update_provider(self.config.ai.reply_provider, ai.get("reply_provider"))
        self._update_provider(self.config.ai.image_provider, ai.get("image_provider"))
        if isinstance(ai.get("reply"), dict):
            self._update_ai_reply_settings(ai["reply"])
        if isinstance(ai.get("image"), dict):
            self._update_ai_image_settings(ai["image"])
        self._sync_ai_module_cards()
        self._apply_ai_module_runtime_changes(previous_enabled)
        self.config.save(self.config_path)
        logger.info("AI config updated from admin UI")
        return self.ai_snapshot()

    def settings_snapshot(self) -> dict[str, Any]:
        return self.config.public_dict()

    def list_groups(self) -> list[dict[str, Any]]:
        if not self.loop:
            raise RuntimeError("Application loop is not ready")
        future = asyncio.run_coroutine_threadsafe(self.telegram.list_groups(), self.loop)
        return future.result(timeout=30)

    def list_targets(self) -> list[dict[str, Any]]:
        if not self.loop:
            raise RuntimeError("Application loop is not ready")
        future = asyncio.run_coroutine_threadsafe(self.telegram.list_targets(), self.loop)
        return future.result(timeout=30)

    def update_settings(self, values: dict[str, Any]) -> None:
        telegram = values.get("telegram", {})
        if isinstance(telegram, dict) and "monitored_groups" in telegram:
            groups = telegram["monitored_groups"]
            if isinstance(groups, list):
                meta = telegram.get("monitored_group_meta")
                self.telegram.update_monitored_groups(groups, meta if isinstance(meta, dict) else None)
        self.config.save(self.config_path)
        logger.info("Settings updated from admin UI")

    def update_module(self, module_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        module = self.modules.get(module_id)
        if module is None:
            return None

        if "enabled" in values:
            enabled = bool(values["enabled"])
            module.card.enabled = enabled
            if hasattr(self.config.modules, module_id):
                setattr(self.config.modules, module_id, enabled)
            if module_id == "ai_reply":
                self.config.ai.reply_provider.enabled = enabled
            elif module_id == "ai_image":
                self.config.ai.image_provider.enabled = enabled
            if self.loop and self.service_state == "running":
                action = module.start if enabled else module.stop
                asyncio.run_coroutine_threadsafe(action(), self.loop)

        if "config" in values and isinstance(values["config"], dict):
            module.update_config(values["config"])
            if module_id == "red_packet" and hasattr(module, "config"):
                self.config.red_packet = module.config
            if module_id == "send_red_packet" and hasattr(module, "config"):
                self.config.send_red_packet = module.config
            if module_id == "ai_decrypt" and hasattr(module, "config"):
                self.config.ai_decrypt = module.config
            if module_id == "gif" and hasattr(module, "config"):
                self.config.gif = module.config
            if module_id == "checkin" and hasattr(module, "config"):
                self.config.checkin = module.config
            if module_id == "auto_forward" and hasattr(module, "config"):
                self.config.auto_forward = module.config
            if module_id == "word_cloud" and hasattr(module, "config"):
                self.config.word_cloud = module.config
            if module_id == "user_profile" and hasattr(module, "config"):
                self.config.user_profile = module.config
            if module_id == "quote" and hasattr(module, "config"):
                self.config.quote = module.config
            if module_id == "chat_games" and hasattr(module, "config"):
                self.config.chat_games = module.config
            if module_id == "magnet_import" and hasattr(module, "config"):
                self.config.magnet_import = module.config

        self.config.save(self.config_path)
        logger.info("Module updated: %s", module_id)
        return module.card.__dict__

    def _public_ai_provider(self, provider: AIProviderConfig) -> dict[str, Any]:
        data = asdict(provider)
        data["has_api_key"] = bool(provider.api_key)
        data["api_key"] = ""
        return data

    def _update_provider(self, provider: AIProviderConfig, values: Any) -> None:
        if not isinstance(values, dict):
            return
        for key in ("name", "provider_type", "base_url", "model"):
            if key in values:
                setattr(provider, key, str(values.get(key) or ""))
        if "enabled" in values:
            provider.enabled = bool(values["enabled"])
        if "api_key" in values and str(values.get("api_key") or "").strip():
            provider.api_key = str(values["api_key"]).strip()

    def _sync_ai_module_cards(self) -> None:
        self.config.modules.ai_reply = self.config.ai.reply_provider.enabled
        self.config.modules.ai_image = self.config.ai.image_provider.enabled
        reply = self.modules.get("ai_reply")
        if reply:
            reply.card.enabled = self.config.ai.reply_provider.enabled
            if hasattr(reply, "update_config"):
                reply.update_config({"reply": asdict(self.config.ai.reply)})
            reply.card.config.update(
                {
                    "provider": self.config.ai.reply_provider.name,
                    "provider_type": self.config.ai.reply_provider.provider_type,
                    "model": self.config.ai.reply_provider.model,
                    "base_url": self.config.ai.reply_provider.base_url,
                    "reply": asdict(self.config.ai.reply),
                }
            )
            if hasattr(reply, "_sync_card_config"):
                reply._sync_card_config()
        image = self.modules.get("ai_image")
        if image:
            image.card.enabled = self.config.ai.image_provider.enabled
            if hasattr(image, "update_config"):
                image.update_config({"image": asdict(self.config.ai.image)})
            image.card.config.update(
                {
                    "provider": self.config.ai.image_provider.name,
                    "provider_type": self.config.ai.image_provider.provider_type,
                    "model": self.config.ai.image_provider.model,
                    "base_url": self.config.ai.image_provider.base_url,
                    "image": asdict(self.config.ai.image),
                }
            )
            if hasattr(image, "_sync_card_config"):
                image._sync_card_config()
        decrypt = self.modules.get("ai_decrypt")
        if decrypt and hasattr(decrypt, "_sync_card_config"):
            decrypt._sync_card_config()

    def _sync_runtime_ai_settings_from_modules(self) -> None:
        image = self.modules.get("ai_image")
        if image and hasattr(image, "reload_runtime_settings"):
            image.reload_runtime_settings()

    def _update_ai_reply_settings(self, values: dict[str, Any]) -> None:
        for key in ("system_prompt", "reasoning_effort", "text_verbosity", "image_detail", "settings_store"):
            if key in values:
                setattr(self.config.ai.reply, key, str(values.get(key) or ""))
        for key in ("command_prefixes", "wake_words", "reply_triggers", "message_info_command_prefixes"):
            if isinstance(values.get(key), list):
                setattr(self.config.ai.reply, key, [str(item).strip() for item in values[key] if str(item).strip()])
        for key in ("context_limit", "max_tokens"):
            if key in values:
                setattr(self.config.ai.reply, key, int(values.get(key) or 0))
        for key in ("timeout_seconds", "temperature"):
            if key in values:
                setattr(self.config.ai.reply, key, float(values.get(key) or 0))
        for key in ("reasoning_summary", "web_search", "message_info_enabled"):
            if key in values:
                setattr(self.config.ai.reply, key, bool(values[key]))

    def _update_ai_image_settings(self, values: dict[str, Any]) -> None:
        for key in ("size", "ratio", "quality", "send_mode", "output_dir", "settings_store"):
            if key in values:
                setattr(self.config.ai.image, key, str(values.get(key) or ""))
        for key in ("command_prefixes", "size_commands", "ratio_commands", "send_mode_commands", "model_commands"):
            if isinstance(values.get(key), list):
                setattr(self.config.ai.image, key, [str(item).strip() for item in values[key] if str(item).strip()])
        if "timeout_seconds" in values:
            self.config.ai.image.timeout_seconds = float(values.get("timeout_seconds") or 0)

    def _apply_ai_module_runtime_changes(self, previous_enabled: dict[str, bool]) -> None:
        if not self.loop or self.service_state != "running":
            return
        for module_id, was_enabled in previous_enabled.items():
            module = self.modules.get(module_id)
            if module is None or bool(module.card.enabled) == was_enabled:
                continue
            action = module.start if module.card.enabled else module.stop
            asyncio.run_coroutine_threadsafe(action(), self.loop)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass
