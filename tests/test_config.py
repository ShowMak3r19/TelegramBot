from __future__ import annotations

from pathlib import Path

from telegram_bot.config import AppConfig


def test_config_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    AppConfig.ensure_file(path)

    config = AppConfig.load(path)
    config.telegram.monitored_groups = ["-1001", "-1002"]
    config.telegram.monitored_group_meta = {
        "-1001": {"title": "主群", "username": "main", "kind": "group"},
        "-1002": {"title": "抽奖频道", "username": "lottery", "kind": "channel"},
    }
    config.save(path)

    loaded = AppConfig.load(path)
    assert loaded.telegram.monitored_groups == ["-1001", "-1002"]
    assert loaded.telegram.monitored_group_meta["-1001"]["title"] == "主群"
    assert loaded.telegram.monitored_group_meta["-1002"]["kind"] == "channel"


def test_ai_provider_type_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig()
    config.ai.reply_provider.provider_type = "claude"
    config.ai.image_provider.provider_type = "openai-compatible"
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.ai.reply_provider.provider_type == "claude"
    assert loaded.ai.image_provider.provider_type == "openai-compatible"


def test_send_red_packet_minimums_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig()
    config.send_red_packet.min_packet_amount = 2
    config.send_red_packet.strict_min_packet_amount = 101
    config.send_red_packet.strict_min_packet_group_ids = ["-1000000000001"]
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.send_red_packet.min_packet_amount == 2
    assert loaded.send_red_packet.strict_min_packet_amount == 101
    assert loaded.send_red_packet.strict_min_packet_group_ids == ["-1000000000001"]


def test_chat_games_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig()
    config.modules.chat_games = True
    config.chat_games.lucky_word.words = ["咖啡"]
    config.chat_games.emoji_riddle.reward_text = "+250"
    config.chat_games.garbled_decode.command_prefixes = ["/decode"]
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.modules.chat_games is True
    assert loaded.chat_games.lucky_word.words == ["咖啡"]
    assert loaded.chat_games.emoji_riddle.reward_text == "+250"
    assert loaded.chat_games.garbled_decode.command_prefixes == ["/decode"]


def test_user_profile_config_roundtrip_and_clamps(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig.from_dict(
        {
            "modules": {"user_profile": True},
            "user_profile": {
                "command_prefixes": ["/who"],
                "default_sample_size": 999,
                "min_sample_size": 5,
                "max_sample_size": 120,
                "min_required_samples": 4,
                "timeout_seconds": 900,
                "max_tokens": 99999,
                "style_prompt": "温和但有梳理感",
            },
        }
    )
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.modules.user_profile is True
    assert loaded.user_profile.command_prefixes == ["/who"]
    assert loaded.user_profile.default_sample_size == 120
    assert loaded.user_profile.max_sample_size == 120
    assert loaded.user_profile.min_required_samples == 4
    assert loaded.user_profile.timeout_seconds == 600
    assert loaded.user_profile.max_tokens == 12000
    assert loaded.user_profile.style_prompt == "温和但有梳理感"


def test_user_profile_sample_limit_supports_two_thousand() -> None:
    config = AppConfig.from_dict(
        {
            "user_profile": {
                "default_sample_size": 9999,
                "max_sample_size": 9999,
            }
        }
    )

    assert config.user_profile.default_sample_size == 2000
    assert config.user_profile.max_sample_size == 2000


def test_chat_history_config_roundtrip_and_clamps(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig.from_dict(
        {
            "chat_history": {
                "enabled": True,
                "database_path": "runtime/custom/chat.sqlite3",
                "max_text_length": 999999,
                "backfill_enabled": True,
                "backfill_batch_size": 999999,
            }
        }
    )
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.chat_history.enabled is True
    assert loaded.chat_history.database_path == "runtime/custom/chat.sqlite3"
    assert loaded.chat_history.max_text_length == 65536
    assert loaded.chat_history.backfill_enabled is True
    assert loaded.chat_history.backfill_batch_size == 5000


def test_user_profile_defaults_include_fx_all_aliases() -> None:
    config = AppConfig()

    assert "/fx" in config.user_profile.command_prefixes
    assert ".fx" in config.user_profile.command_prefixes
    assert "毒舌" in config.user_profile.style_prompt
    assert "适度夸张" in config.user_profile.style_prompt
