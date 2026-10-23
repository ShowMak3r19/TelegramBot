from __future__ import annotations

from types import SimpleNamespace

from telegram_bot.config import GifConfig
from telegram_bot.modules.gif import extract_gif_prompt, format_time_range, media_can_convert, parse_gif_time_range


class DocumentAttributeSticker:
    pass


def test_gif_prompt_uses_configured_prefixes() -> None:
    config = GifConfig(command_prefixes=["/vgif", "动图"])

    assert extract_gif_prompt("/vgif 从头到第十秒", config) == "从头到第十秒"
    assert extract_gif_prompt("动图 从第三秒到最后", config) == "从第三秒到最后"
    assert extract_gif_prompt("普通消息", config) is None


def test_gif_time_range_parses_head_to_tenth_second() -> None:
    assert parse_gif_time_range("从头开始到第十秒") == (0.0, 10.0)
    assert parse_gif_time_range("0-10秒") == (0.0, 10.0)


def test_gif_time_range_parses_start_to_end() -> None:
    assert parse_gif_time_range("从第三秒到最后") == (3.0, None)
    assert format_time_range(3.0, None) == "从 3s 到结尾"


def test_gif_time_range_parses_long_video_minutes() -> None:
    assert parse_gif_time_range("从十一分三十秒到十一分五十秒") == (690.0, 710.0)
    assert parse_gif_time_range("11:30-11:50") == (690.0, 710.0)


def test_gif_accepts_webm_and_webp_telegram_stickers_without_filename() -> None:
    webm_sticker = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="video/webm",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext="", mime_type=""),
    )
    webp_sticker = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="image/webp",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext="", mime_type=""),
    )

    assert media_can_convert(webm_sticker) is True
    assert media_can_convert(webp_sticker) is True


def test_gif_rejects_tgs_sticker_without_lottie_renderer() -> None:
    tgs_sticker = SimpleNamespace(
        media=SimpleNamespace(
            document=SimpleNamespace(
                mime_type="application/x-tgsticker",
                attributes=[DocumentAttributeSticker()],
            )
        ),
        file=SimpleNamespace(name="", ext="", mime_type=""),
    )

    assert media_can_convert(tgs_sticker) is False
