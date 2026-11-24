from pathlib import Path

from telegram_bot.config import AppConfig
from telegram_bot.modules import create_default_registry

ROOT = Path(__file__).resolve().parents[1]


def test_default_configuration_has_no_account_bindings():
    config = AppConfig()
    assert config.project_name == "Telebot"
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
    assert not config.magnet_import.channel_chat
    assert not config.magnet_import.channel_url_prefix
    assert not config.magnet_import.channel_export_chat
    assert not config.magnet_import.avdb_repo
    assert not config.rex_widget_sync.channel_chat
    assert not config.rex_widget_sync.hub_base_url
    assert not config.rex_widget_sync.hub_password
    assert not config.rex_widget_sync.collection_slug
    assert not config.ai.reply_provider.api_key
    assert not config.ai.image_provider.api_key
    assert all(not card["enabled"] for card in create_default_registry(config).cards())


def test_docker_deployment_files_and_security_notice_present():
    assert (ROOT / "Dockerfile").is_file()
    assert (ROOT / "docker-compose.yml").is_file()
    assert (ROOT / ".dockerignore").is_file()
    assert (ROOT / ".github/workflows/docker-publish.yml").is_file()
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ghcr.io/showmak3r19/telegrambot:latest" in compose
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    assert "ghcr.io/showmak3r19/telegrambot:latest" in readme
    assert "没有登录鉴权" in readme
    assert "内网" in readme
    assert "不负责" in readme
    assert "没有登录鉴权" in deployment
    assert "docker compose" in deployment
