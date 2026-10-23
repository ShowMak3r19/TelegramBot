from telegram_bot.config import AppConfig
from telegram_bot.modules import create_default_registry


def test_default_configuration_has_no_account_bindings():
    config = AppConfig()
    assert config.admin.host == "127.0.0.1"
    assert config.telegram.enabled is False
    assert not config.telegram.api_hash
    assert not config.telegram.bot_token
    assert not config.telegram.monitored_groups
    assert not config.telegram.monitored_group_meta
    assert not config.send_red_packet.strict_min_packet_group_ids
    assert not config.magnet_import.watch_chats
    assert not config.magnet_import.sender_usernames
    assert not config.magnet_import.api_password
    assert not config.ai.reply_provider.api_key
    assert not config.ai.image_provider.api_key
    assert all(not card["enabled"] for card in create_default_registry(config).cards())
