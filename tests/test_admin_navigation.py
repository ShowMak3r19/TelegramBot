from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.config import AppConfig
from telegram_bot.modules import create_default_registry


def test_admin_sections_are_balanced_and_panels_belong_to_views() -> None:
    from html.parser import HTMLParser

    class SectionParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []

        def handle_starttag(self, tag, attrs):
            if tag != "section":
                return
            values = dict(attrs)
            classes = values.get("class", "").split()
            if "panel" in classes:
                assert any("view" in parent for parent in self.stack)
            self.stack.append(classes)

        def handle_endtag(self, tag):
            if tag == "section":
                assert self.stack, "Unexpected closing section"
                self.stack.pop()

    parser = SectionParser()
    parser.feed((ROOT / "telegram_bot/admin/static/index.html").read_text(encoding="utf-8"))
    assert not parser.stack


def _module_view_map(app_js: str) -> dict[str, str]:
    match = re.search(r"const moduleViewMap = \{(?P<body>.*?)\};", app_js, re.S)
    assert match is not None, "moduleViewMap is missing from admin app.js"
    return dict(re.findall(r"([a-zA-Z0-9_]+):\s*\"([^\"]+)\"", match.group("body")))


def test_admin_sidebar_covers_registered_feature_modules() -> None:
    admin_static = ROOT / "telegram_bot" / "admin" / "static"
    app_js = (admin_static / "app.js").read_text(encoding="utf-8")
    index_html = (admin_static / "index.html").read_text(encoding="utf-8")

    registered_module_ids = {card["id"] for card in create_default_registry(AppConfig()).cards()}
    module_views = _module_view_map(app_js)

    missing_view_mapping = sorted(registered_module_ids - set(module_views))
    assert missing_view_mapping == []

    missing_nav_items = [
        module_id
        for module_id in sorted(registered_module_ids)
        if f'data-view="{module_views[module_id]}"' not in index_html
    ]
    assert missing_nav_items == []

    missing_sections = [
        module_id
        for module_id in sorted(registered_module_ids)
        if f'id="{module_views[module_id]}"' not in index_html
    ]
    assert missing_sections == []




def test_user_profile_admin_view_has_navigation_config_and_privacy_copy() -> None:
    admin_static = ROOT / "telegram_bot" / "admin" / "static"
    app_js = (admin_static / "app.js").read_text(encoding="utf-8")
    index_html = (admin_static / "index.html").read_text(encoding="utf-8")

    assert 'user_profile: "moduleUserProfile"' in app_js
    assert 'moduleUserProfile: "user_profile"' in app_js
    assert 'moduleUserProfile: ["群友画像"' in app_js
    assert 'data-view="moduleUserProfile"' in index_html
    assert 'id="moduleUserProfile"' in index_html
    assert 'data-icon="user_profile"' in index_html
    assert 'id="userProfileSettingsForm"' in index_html
    assert 'id="saveUserProfileConfig"' in index_html
    assert "fillUserProfileSettings" in app_js
    assert "/fx all" in index_html
    assert "/fx local" in index_html
    assert '["/profile", "/fx", ".fx", "画像", "用户画像"]' in app_js
    assert "collectUserProfileSettings" in app_js
    assert "saveUserProfileConfig" in app_js
    assert "不在本地建立持久用户档案" in index_html
    assert "不推断敏感属性" in index_html
    for field in (
        "command_prefixes",
        "default_sample_size",
        "min_sample_size",
        "max_sample_size",
        "min_required_samples",
        "timeout_seconds",
        "max_tokens",
        "style_prompt",
    ):
        assert f'name="{field}"' in index_html
    assert "命令会原地改为“分析中”" in index_html


def test_ai_provider_forms_offer_chat_completions_channel() -> None:
    index_html = (ROOT / "telegram_bot" / "admin" / "static" / "index.html").read_text(encoding="utf-8")

    assert index_html.count('value="openai-compatible-chat"') == 2
    assert index_html.count("OpenAI-Compatible（Chat Completions）") == 2
    assert index_html.count('value="xai-imagine"') == 1
    assert index_html.count("xAI-Compatible（Imagine Images）") == 1

    app_js = (ROOT / "telegram_bot" / "admin" / "static" / "app.js").read_text(encoding="utf-8")
    assert "normalizeProviderType(providerName, provider.provider_type)" in app_js
    assert '["xai", "xai-compatible", "xai-imagine", "grok-imagine"]' in app_js


def test_send_red_packet_admin_view_uses_existing_multiline_helper() -> None:
    app_js = (ROOT / "telegram_bot" / "admin" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'setFormLines(form, "strict_min_packet_group_ids"' in app_js
    assert "setLinesValue(" not in app_js


def test_red_packet_admin_pre_click_controls_preserve_message_lines() -> None:
    app_js = (ROOT / "telegram_bot" / "admin" / "static" / "app.js").read_text(encoding="utf-8")
    detail_start = app_js.index("function showRedPacketDetail")
    detail_end = app_js.index("function newRedPacketTemplate", detail_start)
    detail_source = app_js[detail_start:detail_end]

    delay_position = detail_source.index('id="redPacketSendDelayMs"')
    messages_position = detail_source.index('id="redPacketPreClickMessages"')
    assert delay_position < messages_position
    assert 'const messageInput = document.getElementById("redPacketPreClickMessages")' in detail_source
    assert re.search(r"preClickMessages\s*=\s*splitRows\(\s*messageInput\.value\s*\)", detail_source)
    assert 'splitLines(document.getElementById("redPacketPreClickMessages").value)' not in detail_source
    assert "pre_click_messages: preClickMessages" in detail_source

    assert "send_message_before_click: false" in app_js
    assert "delay_before_click: true" in app_js
    assert "首次抢后自动发言" in app_js
    assert "发言后延迟再抢" in app_js
    assert "自动发言候选" in detail_source
    assert (
        "按钮模板首次点击不等待；开启“首次抢后自动发言”后：立即点击 → 随机发言 → 可选延迟 → 再次点击。"
        "未开启时延迟不生效。"
    ) in detail_source
    assert (
        "每行一条，首次点击后随机发送；开启延迟时，等待后再次点击。"
        "消息中的逗号会原样保留。"
    ) in detail_source

    for field in ("send_message_before_click", "delay_before_click"):
        assert f'data-field="{field}"' in app_js
        assert f'{field}: card.querySelector(\'[data-field="{field}"]\').checked' in app_js
