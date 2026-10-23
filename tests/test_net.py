from __future__ import annotations

from telegram_bot.shared.net import ensure_http_url


def test_ensure_http_url_allows_http_and_https() -> None:
    assert ensure_http_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
    # 私网地址放行（局域网自建服务场景）
    assert ensure_http_url("http://192.168.1.10:8080/v1") == "http://192.168.1.10:8080/v1"
    assert ensure_http_url("  https://example.com/x  ") == "https://example.com/x"


def test_ensure_http_url_rejects_dangerous_schemes() -> None:
    for bad in ("file:///etc/passwd", "gopher://x", "ftp://h/x", "data:text/plain,x", ""):
        raised = False
        try:
            ensure_http_url(bad)
        except ValueError:
            raised = True
        assert raised, f"expected rejection for {bad!r}"


def test_ensure_http_url_requires_host() -> None:
    raised = False
    try:
        ensure_http_url("http://")
    except ValueError:
        raised = True
    assert raised
