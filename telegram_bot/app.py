from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from . import __version__
from .admin import AdminServer
from .config import AIProviderConfig, AppConfig
from .jobs import ChatHistoryBackfillJob
from .logging_setup import RecentLogBuffer, configure_logging
from .modules import ModuleRegistry, create_default_registry
from .persistence import ChatHistoryStore
from .runtime import RuntimeMetrics, ensure_runtime_dirs, system_snapshot
from .telegram import TelegramAdapter
from .usage import build_ai_usage_stats

T = TypeVar("T")
logger = logging.getLogger(__name__)

MODULE_CONFIG_EXPORT_FORMAT = "telebot-modules-config"
MODULE_CONFIG_EXPORT_VERSION = 1
_MODULE_CONFIG_ATTRS: dict[str, str] = {
    "red_packet": "red_packet",
    "send_red_packet": "send_red_packet",
    "ai_decrypt": "ai_decrypt",
    "gif": "gif",
    "checkin": "checkin",
    "auto_forward": "auto_forward",
    "word_cloud": "word_cloud",
    "user_profile": "user_profile",
    "quote": "quote",
    "chat_games": "chat_games",
    "magnet_import": "magnet_import",
    "rex_widget_sync": "rex_widget_sync",
}
_AI_SUBCONFIG_MODULES = frozenset({"ai_reply", "ai_image"})
_EXPORTABLE_MODULE_IDS = frozenset(_MODULE_CONFIG_ATTRS) | _AI_SUBCONFIG_MODULES
_MODULE_SECRET_FIELDS: dict[str, frozenset[str]] = {
    "magnet_import": frozenset({"api_password"}),
    "rex_widget_sync": frozenset({"hub_password"}),
}


class TelegramBotApplication:
    def __init__(self, config: AppConfig, config_path: Path, project_root: Path | None = None) -> None:
        self.config = config
        self.config_path = config_path
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
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
        send_red_packet = self.modules.get("send_red_packet")
        if send_red_packet is not None:
            send_red_packet.set_history_reader(self.telegram.iter_history_messages)
            self.telegram.add_reconnect_listener(send_red_packet.request_claim_recovery)
        checkin = self.modules.get("checkin")
        if checkin is not None and hasattr(checkin, "set_sender"):
            checkin.set_sender(self.telegram.send_message)
        for module in self.modules.all():
            if hasattr(module, "set_programmatic_message_checker"):
                module.set_programmatic_message_checker(self.telegram.is_programmatic_message)
            if hasattr(module, "set_config_saver"):
                module.set_config_saver(lambda: self.config.save(self.config_path))
        magnet_import = self.modules.get("magnet_import")
        if magnet_import is not None and hasattr(magnet_import, "set_history_reader"):
            magnet_import.set_history_reader(self.telegram.iter_history_messages)
        if magnet_import is not None and hasattr(magnet_import, "set_file_sender"):
            magnet_import.set_file_sender(self.telegram.send_file)
        if magnet_import is not None and hasattr(magnet_import, "request_channel_scan"):
            # 断线期间的频道消息收不到，重连后从游标补漏
            self.telegram.add_reconnect_listener(lambda: magnet_import.request_channel_scan(full=False))
        rex_widget_sync = self.modules.get("rex_widget_sync")
        if rex_widget_sync is not None and hasattr(rex_widget_sync, "set_history_reader"):
            rex_widget_sync.set_history_reader(self.telegram.iter_history_messages)
        self.admin = AdminServer(self)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.service_state = "starting"
        self.dashboard_history: list[dict[str, float]] = []
        self._restarting = False

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
        logger.info("Starting %s %s", self.config.project_name, __version__)
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
        if getattr(self, "_restarting", False):
            logger.warning("Service restart already in progress; ignoring duplicate request")
            return
        self._restarting = True
        await self.stop_service()
        chat_history = getattr(self, "chat_history", None)
        if chat_history is not None and hasattr(chat_history, "close"):
            try:
                chat_history.close()
            except Exception:
                logger.exception("Failed to close chat history before restart")
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
            self._restarting = False
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
            active_results = [result for result in results if result.status != "ignored"]
            if active_results:
                logger.info(
                    "Telegram message module results: %s",
                    ", ".join(f"{result.module_id}={result.status}" for result in active_results),
                )
            elif results:
                logger.debug(
                    "Telegram message module results: %s",
                    ", ".join(f"{result.module_id}={result.status}" for result in results),
                )
            else:
                logger.debug("Telegram message matched no enabled module")
            if any(result.status == "handled" for result in results):
                self.metrics.messages_handled += 1
            if any(result.status == "failed" for result in results):
                self.metrics.failures += 1
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
                "version": __version__,
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

    def _call_on_loop(self, fn: Callable[[], T], *, timeout: float = 15.0) -> T:
        loop = getattr(self, "loop", None)
        if loop is None or not loop.is_running():
            return fn()
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            return fn()

        async def _invoke() -> T:
            return fn()

        return asyncio.run_coroutine_threadsafe(_invoke(), loop).result(timeout=timeout)

    def _schedule_module_action(self, module_id: str, action: Callable[[], Any]) -> None:
        loop = getattr(self, "loop", None)
        if not loop or self.service_state != "running":
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            task = asyncio.create_task(action())
            task.add_done_callback(lambda fut: _log_task_error(module_id, fut))
        else:
            future = asyncio.run_coroutine_threadsafe(action(), loop)
            future.add_done_callback(lambda fut: _log_task_error(module_id, fut))

    def module_statistics_snapshot(self, module_id: str) -> dict[str, Any] | None:
        def _read() -> dict[str, Any] | None:
            module = self.modules.get(module_id)
            if module is None or not hasattr(module, "statistics_snapshot"):
                return None
            return module.statistics_snapshot()

        return self._call_on_loop(_read)

    def update_ai_config(self, values: dict[str, Any]) -> dict[str, Any]:
        return self._call_on_loop(lambda: self._update_ai_config_sync(values))

    def _update_ai_config_sync(self, values: dict[str, Any]) -> dict[str, Any]:
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

    def request_magnet_channel_scan(self, full: bool, rebuild: bool = False) -> bool:
        module = self.modules.get("magnet_import")
        if not self.loop or module is None or not hasattr(module, "request_channel_scan"):
            return False
        if not self.telegram.connected:
            return False

        async def _request() -> bool:
            return module.request_channel_scan(full=full, rebuild=rebuild)

        return asyncio.run_coroutine_threadsafe(_request(), self.loop).result(timeout=10)

    def request_rex_widget_scan(self, full: bool) -> bool:
        module = self.modules.get("rex_widget_sync")
        if not self.loop or module is None or not hasattr(module, "request_scan"):
            return False
        if not self.telegram.connected:
            return False

        async def _request() -> bool:
            return module.request_scan(full=full)

        return asyncio.run_coroutine_threadsafe(_request(), self.loop).result(timeout=10)

    def request_magnet_avdb_run(self, force: bool, rebuild: bool, update_existing: bool = False) -> bool:
        module = self.modules.get("magnet_import")
        if not self.loop or module is None or not hasattr(module, "request_avdb_run"):
            return False

        async def _request() -> bool:
            return module.request_avdb_run(force=force, rebuild=rebuild, update_existing=update_existing)

        return asyncio.run_coroutine_threadsafe(_request(), self.loop).result(timeout=10)

    def run_magnet_channel_export(self) -> dict[str, Any]:
        module = self.modules.get("magnet_import")
        if not self.loop or module is None or not hasattr(module, "run_channel_export"):
            return {"status": "failed", "detail": "模块不可用"}
        return asyncio.run_coroutine_threadsafe(module.run_channel_export(), self.loop).result(timeout=600)

    def update_settings(self, values: dict[str, Any]) -> None:
        def _apply() -> None:
            telegram = values.get("telegram", {})
            if isinstance(telegram, dict) and "monitored_groups" in telegram:
                groups = telegram["monitored_groups"]
                if isinstance(groups, list):
                    meta = telegram.get("monitored_group_meta")
                    self.telegram.update_monitored_groups(groups, meta if isinstance(meta, dict) else None)
            self.config.save(self.config_path)
            logger.info("Settings updated from admin UI")

        self._call_on_loop(_apply)

    def update_module(self, module_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        return self._call_on_loop(lambda: self._update_module_sync(module_id, values))

    def _update_module_sync(self, module_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
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
            action = module.start if enabled else module.stop
            self._schedule_module_action(module_id, action)

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
            if module_id == "rex_widget_sync" and hasattr(module, "config"):
                self.config.rex_widget_sync = module.config

        self.config.save(self.config_path)
        logger.info("Module updated: %s", module_id)
        return module.card.__dict__

    def export_modules_config(self, module_ids: list[str] | None = None) -> dict[str, Any]:
        return self._call_on_loop(lambda: self._export_modules_config_sync(module_ids))

    def _export_modules_config_sync(self, module_ids: list[str] | None = None) -> dict[str, Any]:
        self._sync_runtime_ai_settings_from_modules()
        wanted = (
            {str(item).strip() for item in module_ids if str(item).strip()}
            if module_ids is not None
            else None
        )
        exported_modules: dict[str, dict[str, Any]] = {}
        for module in self.modules.all():
            module_id = module.card.id
            if module_id not in _EXPORTABLE_MODULE_IDS:
                continue
            if wanted is not None and module_id not in wanted:
                continue
            if module_id == "ai_reply":
                cfg_data = asdict(self.config.ai.reply)
            elif module_id == "ai_image":
                cfg_data = asdict(self.config.ai.image)
            else:
                cfg_data = asdict(getattr(self.config, _MODULE_CONFIG_ATTRS[module_id]))
            for secret_key in _MODULE_SECRET_FIELDS.get(module_id, frozenset()):
                cfg_data.pop(secret_key, None)
            exported_modules[module_id] = {
                "name": module.card.name,
                "enabled": bool(module.card.enabled),
                "config": cfg_data,
            }
        if not exported_modules:
            raise ValueError("至少选择一个有效的功能模块")
        return {
            "format": MODULE_CONFIG_EXPORT_FORMAT,
            "schema_version": MODULE_CONFIG_EXPORT_VERSION,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "project": {
                "name": self.config.project_name,
                "version": __version__,
            },
            "excluded": [
                "admin",
                "telegram",
                "logs",
                "runtime",
                "chat_history",
                "ai.reply_provider",
                "ai.image_provider",
                "module_passwords",
            ],
            "modules": exported_modules,
        }

    def import_modules_config(
        self,
        payload: dict[str, Any],
        *,
        module_ids: list[str] | None = None,
        apply_enabled: bool = True,
    ) -> dict[str, Any]:
        return self._call_on_loop(
            lambda: self._import_modules_config_sync(
                payload,
                module_ids=module_ids,
                apply_enabled=apply_enabled,
            )
        )

    def _import_modules_config_sync(
        self,
        payload: dict[str, Any],
        *,
        module_ids: list[str] | None = None,
        apply_enabled: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("导入内容必须是 JSON 对象")
        fmt = payload.get("format")
        if fmt is not None and str(fmt).strip() != MODULE_CONFIG_EXPORT_FORMAT:
            raise ValueError("不支持的配置文件格式，请使用功能模块导出的 JSON 文件")
        raw_modules = payload.get("modules")
        if not isinstance(raw_modules, dict) or not raw_modules:
            raise ValueError("配置文件中缺少有效的 modules 字段")

        wanted = (
            {str(item).strip() for item in module_ids if str(item).strip()}
            if module_ids is not None
            else None
        )
        registered_map = {m.card.id: m for m in self.modules.all() if m.card.id in _EXPORTABLE_MODULE_IDS}
        ignored = sorted(key for key in raw_modules if key not in registered_map)
        targets: list[tuple[str, Any, dict[str, Any]]] = []
        for module in self.modules.all():
            module_id = module.card.id
            if module_id not in registered_map or module_id not in raw_modules:
                continue
            if wanted is not None and module_id not in wanted:
                continue
            entry = raw_modules[module_id]
            if not isinstance(entry, dict):
                raise ValueError(f"模块 {module_id} 配置格式无效")
            targets.append((module_id, module, entry))

        if not targets:
            raise ValueError("未找到可导入的功能模块")

        ai_targeted = any(module_id in _AI_SUBCONFIG_MODULES for module_id, _, _ in targets)
        previous_ai_enabled: dict[str, bool] = {}
        if ai_targeted:
            self._sync_runtime_ai_settings_from_modules()
            previous_ai_enabled = {
                mid: bool(mod.card.enabled)
                for mid in ("ai_reply", "ai_image")
                if (mod := self.modules.get(mid)) is not None
            }

        imported: list[str] = []
        for module_id, module, entry in targets:
            cfg_in = entry.get("config")
            if module_id == "ai_reply":
                if isinstance(cfg_in, dict):
                    self._update_ai_reply_settings(cfg_in)
                if apply_enabled and "enabled" in entry:
                    self.config.ai.reply_provider.enabled = bool(entry["enabled"])
            elif module_id == "ai_image":
                if isinstance(cfg_in, dict):
                    self._update_ai_image_settings(cfg_in)
                if apply_enabled and "enabled" in entry:
                    self.config.ai.image_provider.enabled = bool(entry["enabled"])
            else:
                if isinstance(cfg_in, dict):
                    cleaned = dict(cfg_in)
                    for secret_key in _MODULE_SECRET_FIELDS.get(module_id, frozenset()):
                        if not str(cleaned.get(secret_key) or "").strip():
                            cleaned.pop(secret_key, None)
                    module.update_config(cleaned)
                    if hasattr(module, "config"):
                        setattr(self.config, _MODULE_CONFIG_ATTRS[module_id], module.config)
                if apply_enabled and "enabled" in entry:
                    enabled = bool(entry["enabled"])
                    changed = bool(module.card.enabled) != enabled
                    module.card.enabled = enabled
                    if hasattr(self.config.modules, module_id):
                        setattr(self.config.modules, module_id, enabled)
                    if changed:
                        self._schedule_module_action(module_id, module.start if enabled else module.stop)
            imported.append(module_id)

        if ai_targeted:
            self._sync_ai_module_cards()
            self._apply_ai_module_runtime_changes(previous_ai_enabled)

        self.config.save(self.config_path)
        logger.info("Modules config imported: modules=%s apply_enabled=%s", imported, apply_enabled)
        return {
            "imported": imported,
            "ignored": ignored,
            "apply_enabled": bool(apply_enabled),
            "modules": self.modules.cards(),
            "ai": self.ai_snapshot(),
        }

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
        reply = self.modules.get("ai_reply")
        if reply and hasattr(reply, "reload_runtime_settings"):
            reply.reload_runtime_settings()
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
            if key in values and values.get(key) is not None and values.get(key) != "":
                parsed_int = int(values[key])
                if parsed_int < 0:
                    raise ValueError(f"{key} 不能为负数")
                setattr(self.config.ai.reply, key, parsed_int)
        for key in ("timeout_seconds", "temperature"):
            if key in values and values.get(key) is not None and values.get(key) != "":
                parsed_float = float(values[key])
                if not math.isfinite(parsed_float):
                    raise ValueError(f"{key} 必须为有限数字")
                if key == "timeout_seconds":
                    parsed_float = max(5.0, min(parsed_float, 600.0))
                else:
                    parsed_float = max(0.0, min(parsed_float, 2.0))
                setattr(self.config.ai.reply, key, parsed_float)
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
        if "timeout_seconds" in values and values.get("timeout_seconds") is not None and values.get("timeout_seconds") != "":
            parsed = float(values["timeout_seconds"])
            if not math.isfinite(parsed):
                raise ValueError("timeout_seconds 必须为有限数字")
            self.config.ai.image.timeout_seconds = max(5.0, min(parsed, 600.0))

    def _apply_ai_module_runtime_changes(self, previous_enabled: dict[str, bool]) -> None:
        if not self.loop or self.service_state != "running":
            return
        for module_id, was_enabled in previous_enabled.items():
            module = self.modules.get(module_id)
            if module is None or bool(module.card.enabled) == was_enabled:
                continue
            action = module.start if module.card.enabled else module.stop
            self._schedule_module_action(module_id, action)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            except NotImplementedError:
                pass


def _log_task_error(module_id: str, future: Any) -> None:
    try:
        exc = future.exception()
    except Exception:
        return
    if exc is not None:
        logger.error("Module lifecycle action failed: %s", module_id, exc_info=exc)
