from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.app import TelegramBotApplication
from telegram_bot.config import AppConfig
from telegram_bot.modules import create_default_registry


def test_default_modules_are_registered() -> None:
    registry = create_default_registry(AppConfig())
    ids = {card["id"] for card in registry.cards()}
    assert {
        "red_packet",
        "send_red_packet",
        "ai_reply",
        "ai_image",
        "word_cloud",
        "user_profile",
        "chat_games",
    } <= ids


def test_user_profile_admin_update_persists_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    app = TelegramBotApplication(AppConfig(), config_path, project_root=tmp_path)

    updated = app.update_module(
        "user_profile",
        {
            "enabled": True,
            "config": {
                "command_prefixes": ["/who"],
                "default_sample_size": 60,
                "min_sample_size": 10,
                "max_sample_size": 120,
                "min_required_samples": 6,
                "style_prompt": "像群聊编辑一样简练",
            },
        },
    )

    assert updated is not None
    assert updated["enabled"] is True
    assert updated["config"]["default_sample_size"] == 60
    assert app.config.user_profile.style_prompt == "像群聊编辑一样简练"
    persisted = AppConfig.load(config_path)
    assert persisted.modules.user_profile is True
    assert persisted.user_profile.command_prefixes == ["/who"]


def test_ai_module_toggle_syncs_provider_enabled(tmp_path: Path) -> None:
    app = TelegramBotApplication(AppConfig(), tmp_path / "config.json", project_root=tmp_path)

    reply = app.update_module("ai_reply", {"enabled": True})
    image = app.update_module("ai_image", {"enabled": True})

    assert reply and reply["enabled"] is True
    assert image and image["enabled"] is True
    assert app.config.modules.ai_reply is True
    assert app.config.modules.ai_image is True
    assert app.config.ai.reply_provider.enabled is True
    assert app.config.ai.image_provider.enabled is True


def test_ai_service_provider_type_updates_from_admin(tmp_path: Path) -> None:
    app = TelegramBotApplication(AppConfig(), tmp_path / "config.json", project_root=tmp_path)

    snapshot = app.update_ai_config(
        {
            "ai": {
                "reply_provider": {
                    "name": "sub2api-chat",
                    "provider_type": "openai-compatible-chat",
                    "model": "gpt-5.6-sol",
                },
                "image_provider": {"name": "openai-image", "provider_type": "openai", "model": "gpt-image-2"},
            }
        }
    )

    assert snapshot["providers"]["reply"]["provider_type"] == "openai-compatible-chat"
    assert app.modules.get("ai_reply").card.config["provider_type"] == "openai-compatible-chat"
    assert app.modules.get("ai_image").card.config["provider_type"] == "openai"


def test_ai_image_runtime_command_settings_sync_to_admin_snapshot(tmp_path: Path) -> None:
    settings_path = tmp_path / "image_settings.json"
    config = AppConfig()
    config.ai.image.settings_store = str(settings_path)
    app = TelegramBotApplication(config, tmp_path / "config.json", project_root=tmp_path)
    settings_path.write_text(
        json.dumps({"size": "4K", "ratio": "auto", "model": "gpt-image-2", "send_mode": "always"}),
        encoding="utf-8",
    )

    snapshot = app.ai_snapshot()
    updated = app.update_ai_config({"ai": {"image": {"timeout_seconds": 333}}})

    assert snapshot["image"]["size"] == "4K"
    assert snapshot["image"]["ratio"] == "auto"
    assert snapshot["providers"]["image"]["model"] == "gpt-image-2"
    assert updated["image"]["size"] == "4K"
    assert updated["image"]["timeout_seconds"] == 333


def test_red_packet_admin_update_persists_pre_click_settings() -> None:
    with TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        app = TelegramBotApplication(AppConfig(), config_path, project_root=Path(tmp))
        values = {
            "send_delay_ms": 1750,
            "pre_click_messages": ["hello, world", "second line"],
            "templates": [
                {
                    "id": "button-red-packet",
                    "name": "Button packet",
                    "enabled": True,
                    "trigger_keywords": ["button packet"],
                    "id_markers": [],
                    "passphrase_markers": [],
                    "button_texts": ["Claim"],
                    "passphrase": "",
                    "send_message_before_click": True,
                    "delay_before_click": True,
                }
            ],
        }

        updated = app.update_module("red_packet", {"config": values})

        assert updated is not None
        assert updated["config"]["send_delay_ms"] == 1750
        assert updated["config"]["pre_click_messages"] == ["hello, world", "second line"]
        assert updated["config"]["templates"][0]["send_message_before_click"] is True
        assert updated["config"]["templates"][0]["delay_before_click"] is True

        module = app.modules.get("red_packet")
        assert module is not None
        assert module.config is app.config.red_packet
        assert module.config.pre_click_messages == ["hello, world", "second line"]
        assert module.config.templates[0].send_message_before_click is True
        assert module.config.templates[0].delay_before_click is True

        persisted = AppConfig.load(config_path)

    assert persisted.red_packet.send_delay_ms == 1750
    assert persisted.red_packet.pre_click_messages == ["hello, world", "second line"]
    assert persisted.red_packet.templates[0].send_message_before_click is True
    assert persisted.red_packet.templates[0].delay_before_click is True


def test_module_config_export_excludes_system_ai_services_and_passwords(tmp_path: Path) -> None:
    config = AppConfig()
    config.admin.username = "admin_user"
    config.admin.password = "admin_secret_pw"
    config.telegram.api_id = 123456
    config.telegram.api_hash = "tg_secret_hash"
    config.telegram.bot_token = "12345:bot_secret"
    config.telegram.monitored_groups = ["-1000000000099"]
    config.ai.reply_provider.base_url = "https://private-reply.example/v1"
    config.ai.reply_provider.api_key = "sk-reply-secret-key"
    config.ai.reply_provider.model = "private-reply-model"
    config.ai.image_provider.base_url = "https://private-image.example/v1"
    config.ai.image_provider.api_key = "sk-image-secret-key"
    config.ai.image_provider.model = "gpt-image-2.5"
    config.ai.reply.system_prompt = "自定义人设提示词"
    config.ai.image.size = "2K"
    config.magnet_import.api_password = "magnet_secret_password"
    config.rex_widget_sync.hub_password = "rex_secret_password"
    config.modules.red_packet = True
    config.red_packet.send_delay_ms = 900

    app = TelegramBotApplication(config, tmp_path / "config.json", project_root=tmp_path)
    exported = app.export_modules_config()

    assert exported["format"] == "telebot-modules-config"
    assert set(exported["modules"]) == {card["id"] for card in app.modules.cards()}
    dumped = json.dumps(exported, ensure_ascii=False)
    for forbidden in (
        "admin_secret_pw",
        "tg_secret_hash",
        "12345:bot_secret",
        "sk-reply-secret-key",
        "sk-image-secret-key",
        "https://private-reply.example/v1",
        "https://private-image.example/v1",
        "private-reply-model",
        "gpt-image-2.5",
        "magnet_secret_password",
        "rex_secret_password",
    ):
        assert forbidden not in dumped

    assert exported["modules"]["ai_reply"]["config"]["system_prompt"] == "自定义人设提示词"
    assert exported["modules"]["ai_image"]["config"]["size"] == "2K"
    assert "api_password" not in exported["modules"]["magnet_import"]["config"]
    assert "hub_password" not in exported["modules"]["rex_widget_sync"]["config"]
    assert exported["modules"]["red_packet"]["enabled"] is True
    assert exported["modules"]["red_packet"]["config"]["send_delay_ms"] == 900

    # 选择性导出会忽略非功能模块键
    partial = app.export_modules_config(["red_packet", "admin", "telegram", "reply_provider"])
    assert list(partial["modules"].keys()) == ["red_packet"]


def test_module_config_import_is_isolated_preserves_passwords_and_respects_flags(tmp_path: Path) -> None:
    source_cfg = AppConfig()
    source_cfg.modules.red_packet = True
    source_cfg.red_packet.send_delay_ms = 1234
    source_cfg.modules.ai_reply = True
    source_cfg.ai.reply_provider.enabled = True
    source_cfg.ai.reply.system_prompt = "导入后的提示词"
    source_cfg.ai.reply.context_limit = 12
    source_cfg.modules.magnet_import = True
    source_cfg.magnet_import.reply_text = "导入后的致谢"
    source_cfg.magnet_import.api_password = "source_password_should_not_export"
    source_cfg.rex_widget_sync.collection_slug = "imported_slug"
    source_cfg.rex_widget_sync.hub_password = "source_hub_pw_should_not_export"

    source_app = TelegramBotApplication(source_cfg, tmp_path / "src.json", project_root=tmp_path / "src")
    bundle = source_app.export_modules_config(["red_packet", "ai_reply", "magnet_import", "rex_widget_sync"])
    # 模拟恶意/手工注入系统与 AI 服务字段
    bundle["admin"] = {"username": "hacker", "password": "pw"}
    bundle["telegram"] = {"api_hash": "hijacked"}
    bundle["ai"] = {"reply_provider": {"api_key": "hijacked"}}
    bundle["modules"]["admin"] = {"enabled": True, "config": {"password": "pw"}}

    target_cfg = AppConfig()
    target_cfg.admin.username = "keep_admin"
    target_cfg.admin.password = "keep_admin_pw"
    target_cfg.telegram.api_hash = "keep_tg_hash"
    target_cfg.ai.reply_provider.api_key = "keep_reply_key"
    target_cfg.ai.reply_provider.model = "keep_reply_model"
    target_cfg.ai.image_provider.model = "gpt-image-2.5"
    target_cfg.magnet_import.api_password = "keep_target_magnet_pw"
    target_cfg.rex_widget_sync.hub_password = "keep_target_hub_pw"
    target_cfg.modules.red_packet = False
    target_cfg.modules.ai_reply = False

    target_path = tmp_path / "target.json"
    target_app = TelegramBotApplication(target_cfg, target_path, project_root=tmp_path / "dst")

    # 1) 仅导入参数不改开关（apply_enabled=False）且仅选 3 个模块
    res1 = target_app.import_modules_config(
        bundle,
        module_ids=["ai_reply", "magnet_import", "rex_widget_sync"],
        apply_enabled=False,
    )
    assert set(res1["imported"]) == {"ai_reply", "magnet_import", "rex_widget_sync"}
    assert "admin" in res1["ignored"]
    assert target_app.config.modules.ai_reply is False
    assert target_app.config.modules.magnet_import is False
    assert target_app.config.ai.reply.system_prompt == "导入后的提示词"
    assert target_app.config.ai.reply.context_limit == 12
    assert target_app.config.magnet_import.reply_text == "导入后的致谢"
    assert target_app.config.magnet_import.api_password == "keep_target_magnet_pw"
    assert target_app.config.rex_widget_sync.collection_slug == "imported_slug"
    assert target_app.config.rex_widget_sync.hub_password == "keep_target_hub_pw"
    # 系统配置和 AI 服务连接绝对未被修改
    assert target_app.config.admin.username == "keep_admin"
    assert target_app.config.admin.password == "keep_admin_pw"
    assert target_app.config.telegram.api_hash == "keep_tg_hash"
    assert target_app.config.ai.reply_provider.api_key == "keep_reply_key"
    assert target_app.config.ai.reply_provider.model == "keep_reply_model"
    assert target_app.config.ai.image_provider.model == "gpt-image-2.5"
    # 未勾选的 red_packet 保持原值
    assert target_app.config.red_packet.send_delay_ms == 0

    # 2) 导入并应用启用状态（apply_enabled=True）
    res2 = target_app.import_modules_config(bundle, module_ids=["red_packet", "ai_reply"], apply_enabled=True)
    assert set(res2["imported"]) == {"red_packet", "ai_reply"}
    assert target_app.config.modules.red_packet is True
    assert target_app.config.red_packet.send_delay_ms == 1234
    assert target_app.config.modules.ai_reply is True
    assert target_app.config.ai.reply_provider.enabled is True

    persisted = AppConfig.load(target_path)
    assert persisted.red_packet.send_delay_ms == 1234
    assert persisted.ai.reply.system_prompt == "导入后的提示词"
    assert persisted.ai.reply_provider.model == "keep_reply_model"
    assert persisted.magnet_import.api_password == "keep_target_magnet_pw"


def test_ai_image_model_persists_across_restart_and_runtime_store(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    settings_path = tmp_path / "runtime" / "data" / "image_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"size": "1K", "ratio": "auto", "model": "gpt-image-2", "send_mode": "auto"}),
        encoding="utf-8",
    )

    config = AppConfig()
    config.ai.image_provider.model = "gpt-image-2"
    app = TelegramBotApplication(config, config_path, project_root=tmp_path)

    updated = app.update_ai_config(
        {
            "ai": {
                "image_provider": {
                    "name": "image",
                    "provider_type": "openai-compatible",
                    "model": "gpt-image-2.5",
                }
            }
        }
    )
    assert updated["providers"]["image"]["model"] == "gpt-image-2.5"
    assert json.loads(settings_path.read_text(encoding="utf-8"))["model"] == "gpt-image-2.5"

    # 模拟服务重启：从磁盘重新加载 config.json 并重建应用，模型必须保持 gpt-image-2.5
    reloaded = TelegramBotApplication(AppConfig.load(config_path), config_path, project_root=tmp_path)
    assert reloaded.config.ai.image_provider.model == "gpt-image-2.5"
    assert reloaded.ai_snapshot()["providers"]["image"]["model"] == "gpt-image-2.5"
