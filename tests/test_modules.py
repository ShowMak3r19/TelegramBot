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
    app = TelegramBotApplication(AppConfig(), config_path)

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
    app = TelegramBotApplication(AppConfig(), tmp_path / "config.json")

    reply = app.update_module("ai_reply", {"enabled": True})
    image = app.update_module("ai_image", {"enabled": True})

    assert reply and reply["enabled"] is True
    assert image and image["enabled"] is True
    assert app.config.modules.ai_reply is True
    assert app.config.modules.ai_image is True
    assert app.config.ai.reply_provider.enabled is True
    assert app.config.ai.image_provider.enabled is True




def test_ai_service_provider_type_updates_from_admin(tmp_path: Path) -> None:
    app = TelegramBotApplication(AppConfig(), tmp_path / "config.json")

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
    app = TelegramBotApplication(config, tmp_path / "config.json")
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
        app = TelegramBotApplication(AppConfig(), config_path)
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
