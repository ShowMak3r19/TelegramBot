from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from telegram_bot.admin.server import _safe_next_url
from telegram_bot.config import (
    AppConfig,
    ChatGamesConfig,
    EmojiRiddleConfig,
    EmojiRiddleItemConfig,
    GarbledDecodeConfig,
    LogConfig,
    LuckyWordConfig,
    MagnetImportConfig,
    RedPacketConfig,
    RedPacketTemplateConfig,
)
from telegram_bot.logging_setup import read_log_tail
from telegram_bot.modules.ai_reply import AIReplyModule, strip_first_wake_word
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.chat_games import ChatGamesModule, extract_decode_start
from telegram_bot.modules.checkin import _parse_cron
from telegram_bot.modules.gif import extract_command_prompt, parse_gif_time_range
from telegram_bot.modules.magnet_avdb import AvdbReleaseImporter
from telegram_bot.modules.magnet_channel import ChannelMagnetImporter
from telegram_bot.modules.quote import parse_quote_command
from telegram_bot.modules.red_packet import RedPacketModule, _matching_button_text
from telegram_bot.modules.send_red_packet import (
    parse_create_command,
    parse_math_quiz_command,
    split_amounts,
)
from telegram_bot.shared.avdb_release import AvdbReleaseError, ReleaseAsset, latest_asset_sync


def test_config_public_dict_masks_rex_hub_password_and_ignores_unknown_keys() -> None:
    cfg = AppConfig.from_dict(
        {
            "unknown_top_level": 123,
            "admin": {"port": 9000, "unexpected_field": "ignored"},
            "rex_widget_sync": {"hub_password": "top-secret-hub-password"},
            "chat_games": {"lucky_word": {"daily_limit_per_chat": 0, "per_user_daily_limit": 0}},
            "magnet_import": {"reply_text": ""},
        }
    )
    assert cfg.admin.port == 9000
    assert cfg.chat_games.lucky_word.daily_limit_per_chat == 0
    assert cfg.chat_games.lucky_word.per_user_daily_limit == 0
    assert cfg.magnet_import.reply_text == ""
    public = cfg.public_dict()
    assert public["rex_widget_sync"]["hub_password"] != "top-secret-hub-password"
    assert "***" in public["rex_widget_sync"]["hub_password"]


def test_admin_safe_next_path_blocks_open_redirects() -> None:
    assert _safe_next_url("/dashboard") == "/dashboard"
    assert _safe_next_url("//evil.example/phish") == "/"
    assert _safe_next_url("/\\evil.example/phish") == "/"
    assert _safe_next_url("https://evil.example") == "/"
    assert _safe_next_url("") == "/"


def test_read_log_tail_zero_lines_returns_empty(tmp_path: Path) -> None:
    log_cfg = LogConfig(dir="logs")
    log_file = tmp_path / "logs" / "test.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert read_log_tail(log_cfg, tmp_path, "test.log", lines=0) == ""
    assert read_log_tail(log_cfg, tmp_path, "test.log", lines=-5) == ""
    assert read_log_tail(log_cfg, tmp_path, "test.log", lines=2) == "line2\nline3\n"


def test_avdb_path_traversal_sanitized_and_script_escape_blocked(tmp_path: Path) -> None:
    with pytest.raises(AvdbReleaseError):
        latest_asset_sync("../bad/repo", r"^.*\.zip$")

    # 越界转换脚本路径应被拒绝
    cfg = MagnetImportConfig(
        api_username="admin",
        api_password="secret",
        avdb_converter_script="../../outside.sh",
    )
    importer = AvdbReleaseImporter(
        lambda: cfg,
        {},
        lambda: None,
        lambda: tmp_path / "work",
        tmp_path,
        latest=lambda repo, pat: ReleaseAsset("../../pwn", "../../evil.zip", "https://example.invalid/a.zip", 0, ""),
    )
    result = asyncio.run(importer.run_once(force=True))
    assert result["status"] == "failed"
    assert "越界" in result["detail"]

    # 恶意 tag / asset name 被限制在 TemporaryDirectory 内
    downloaded_paths: list[Path] = []
    cfg2 = MagnetImportConfig(
        api_username="admin",
        api_password="secret",
        avdb_converter_script="scripts/avdb/resource_to_csv.sh",
    )

    def fake_download(asset: ReleaseAsset, dest: Path) -> Path:
        downloaded_paths.append(dest)
        dest.write_bytes(b"zip")
        return dest

    def fake_convert(script: Path, zip_path: Path) -> Path:
        csv_out = zip_path.with_suffix(".csv")
        csv_out.write_text("title,magnets,source_site,created_at,magnet_hash\n", encoding="utf-8")
        return csv_out

    importer2 = AvdbReleaseImporter(
        lambda: cfg2,
        {},
        lambda: None,
        lambda: tmp_path / "work",
        tmp_path,
        latest=lambda repo, pat: ReleaseAsset("../../escape", "../../payload.zip", "https://example.invalid/a.zip", 0, ""),
        download=fake_download,
        convert=fake_convert,
        exporter=lambda *a, **k: "id,source_site,magnets\n",
        importer=lambda *a, **k: {"data": {}},
    )
    result2 = asyncio.run(importer2.run_once(force=True))
    assert result2["status"] == "imported"
    assert downloaded_paths
    assert (tmp_path / "work").resolve() in downloaded_paths[0].resolve().parents


def test_channel_schedule_scan_does_not_stick_scanning_without_loop(tmp_path: Path) -> None:
    cfg = MagnetImportConfig(channel_enabled=True, channel_chat="-1001")
    channel = ChannelMagnetImporter(
        lambda: cfg,
        {},
        lambda: None,
        lambda *a, **k: {},
        lambda: tmp_path,
    )

    async def dummy_reader(chat, *, min_id=0):
        if False:
            yield None

    channel.history_reader = dummy_reader
    with pytest.raises(RuntimeError):
        channel.schedule_scan(full=False)
    assert channel.scanning is False


def test_ai_reply_wake_word_boundary_and_edited_event_guard(tmp_path: Path) -> None:
    assert strip_first_wake_word("contact email@ai.com please", ["@ai"]) is None
    assert strip_first_wake_word("/ai_status @ai", ["@ai"]) is None
    assert strip_first_wake_word("@ai 你好", ["@ai"]) == "你好"

    cfg = AppConfig()
    module = AIReplyModule(
        ModuleCard("ai_reply", "AI", "", "ai", enabled=True),
        cfg.ai,
        project_root=tmp_path,
    )
    edited_event = SimpleNamespace(
        _tgbot_edited=True,
        message=SimpleNamespace(raw_text="/ai hello", out=True, sender_id=1, chat_id=-1, id=10),
    )
    assert asyncio.run(module.handle_message(edited_event)).status == "ignored"


def test_send_red_packet_prefix_boundary_and_large_split() -> None:
    assert parse_create_command("红包抢完了吗", ["红包"]) is None
    assert parse_create_command("红包 100 2 口令", ["红包"]) == {
        "total_amount": 100,
        "packet_count": 2,
        "passphrase": "口令",
    }
    assert parse_math_quiz_command("/mathquiz 100", ["/math"]) is None
    assert parse_math_quiz_command("/math 100", ["/math"]) == {"reward_amount": 100}

    amounts = split_amounts(10**11, 5, random.Random(42))
    assert len(amounts) == 5
    assert sum(amounts) == 10**11
    assert all(a >= 2 for a in amounts)


def test_quote_and_gif_command_boundaries_and_inverted_range() -> None:
    assert parse_quote_command("/quiz", ["/q"]) is None
    assert parse_quote_command("/quit", ["/q"]) is None
    assert parse_quote_command("/q@mybot 2", ["/q"]) == {"kind": "generate", "count": 2, "with_reply": False}
    assert extract_command_prompt("/vgif2 0-5s", ["/vgif"]) is None
    with pytest.raises(ValueError):
        parse_gif_time_range("10秒到5秒")


def test_chat_games_decode_start_and_random_winner_policy(tmp_path: Path) -> None:
    parsed = extract_decode_start("/decode 2026年快乐", ["/decode"], "+100")
    assert parsed is not None
    assert parsed.reward_text == "+100"
    assert parsed.phrase == "2026年快乐"

    parsed_plus = extract_decode_start("/decode 2026年快乐 +300", ["/decode"], "+100")
    assert parsed_plus is not None
    assert parsed_plus.reward_text == "+300"
    assert parsed_plus.phrase == "2026年快乐"

    # winner_policy="random" 时不应在第一个正确答案时立即结算，而应等到倒计时结束
    config = ChatGamesConfig(
        lucky_word=LuckyWordConfig(enabled=False),
        emoji_riddle=EmojiRiddleConfig(
            duration_seconds=0.12,
            winner_policy="random",
            announce_answer=False,
            items=[EmojiRiddleItemConfig("🔥 + 🧊", ["冰火"])],
        ),
        garbled_decode=GarbledDecodeConfig(enabled=False),
        state_store=str(tmp_path / "cg.json"),
        output_dir=str(tmp_path / "cg_out"),
    )
    module = ChatGamesModule(ModuleCard("chat_games", "cg", "", "game", enabled=True), config, tmp_path)
    sent: list[dict[str, object]] = []

    class FakeClient:
        async def send_file(self, chat_id, **kwargs):
            return SimpleNamespace(id=101)

        async def send_message(self, chat_id, text, **kwargs):
            sent.append({"chat_id": chat_id, "text": text, **kwargs})
            return SimpleNamespace(id=102)

    client = FakeClient()

    async def scenario() -> None:
        start_msg = SimpleNamespace(raw_text="/emoji", out=True, chat_id=-100, sender_id=1, id=1)
        await module.handle_message(SimpleNamespace(message=start_msg, chat_id=-100, sender_id=1, client=client))
        ans1 = SimpleNamespace(raw_text="冰火", out=False, chat_id=-100, sender_id=2, id=2)
        await module.handle_message(SimpleNamespace(message=ans1, chat_id=-100, sender_id=2, client=client))
        assert sent == []  # 尚未开奖
        ans2 = SimpleNamespace(raw_text="冰火", out=False, chat_id=-100, sender_id=3, id=3)
        await module.handle_message(SimpleNamespace(message=ans2, chat_id=-100, sender_id=3, client=client))
        await asyncio.sleep(0.2)
        await module.stop()

    asyncio.run(scenario())
    assert len(sent) == 1
    assert sent[0]["reply_to"] in {2, 3}


def test_checkin_weekday_step_does_not_include_sunday() -> None:
    parsed = _parse_cron("0 9 * * 1/2")
    assert parsed.weekday == frozenset({1, 3, 5})
    assert _parse_cron("0 9 * * 7").weekday == frozenset({0})


def test_red_packet_button_preserves_raw_spacing_and_no_marker_literal_id() -> None:
    msg = SimpleNamespace(buttons=[[SimpleNamespace(text=" 抢红包 ")]])
    assert _matching_button_text(msg, ["抢红包"]) == " 抢红包 "

    module = RedPacketModule(
        ModuleCard("red_packet", "rp", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="t1",
                    trigger_keywords=["红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["口令:"],
                )
            ]
        ),
    )
    assert module.extract_red_packet_id("红包来了\n红包ID:\n", module.config.templates[0]) == ""
    assert json.loads(Path("config.example.json").read_text(encoding="utf-8"))["admin"]["password"] == ""
