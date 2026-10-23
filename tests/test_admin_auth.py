from __future__ import annotations

import base64
from dataclasses import dataclass

from telegram_bot.admin.server import _admin_auth_enabled, _basic_auth_ok, _session_auth_ok


@dataclass
class _Admin:
    username: str = ""
    password: str = ""


def _header(user: str, pwd: str) -> str:
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def test_admin_auth_disabled_when_credentials_missing() -> None:
    assert _admin_auth_enabled(_Admin("", "")) is False
    assert _admin_auth_enabled(_Admin("admin", "")) is False
    assert _admin_auth_enabled(_Admin("", "secret")) is False


def test_admin_auth_enabled_when_both_set() -> None:
    assert _admin_auth_enabled(_Admin("admin", "secret")) is True


def test_basic_auth_accepts_correct_credentials() -> None:
    assert _basic_auth_ok(_header("admin", "secret"), "admin", "secret") is True


def test_basic_auth_rejects_wrong_credentials() -> None:
    assert _basic_auth_ok(_header("admin", "nope"), "admin", "secret") is False
    assert _basic_auth_ok(_header("root", "secret"), "admin", "secret") is False


def test_basic_auth_rejects_malformed_header() -> None:
    assert _basic_auth_ok("", "admin", "secret") is False
    assert _basic_auth_ok("Bearer xyz", "admin", "secret") is False
    assert _basic_auth_ok("Basic not-base64!!", "admin", "secret") is False


def test_session_auth_accepts_active_cookie_token() -> None:
    assert _session_auth_ok("telegrambot_admin_session=abc123", {"abc123"}) is True
    assert _session_auth_ok("telegrambot_admin_session=missing", {"abc123"}) is False
    assert _session_auth_ok("", {"abc123"}) is False
