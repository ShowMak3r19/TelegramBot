from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from telegram_bot.app import TelegramBotApplication


class _ProcessReplaced(BaseException):
    pass


def _bare_application() -> TelegramBotApplication:
    app = object.__new__(TelegramBotApplication)
    app.config_path = Path("config.json")
    app.stop_service = AsyncMock()
    app.start_service = AsyncMock()
    return app


def test_restart_service_replaces_the_python_process() -> None:
    app = _bare_application()
    exec_call: dict[str, object] = {}

    def fake_execv(path: str, argv: list[str]) -> None:
        exec_call.update(path=path, argv=argv)
        raise _ProcessReplaced

    with patch("telegram_bot.app.os.execv", side_effect=fake_execv):
        with pytest.raises(_ProcessReplaced):
            asyncio.run(app.restart_service())

    app.stop_service.assert_awaited_once_with()
    app.start_service.assert_not_awaited()
    assert exec_call == {
        "path": sys.executable,
        "argv": [sys.executable, "-m", "telegram_bot", "--config", "config.json"],
    }


def test_restart_service_recovers_when_process_replacement_fails() -> None:
    app = _bare_application()

    def fail_execv(path: str, argv: list[str]) -> None:
        raise OSError("exec failed")

    with patch("telegram_bot.app.os.execv", side_effect=fail_execv):
        with pytest.raises(OSError, match="exec failed"):
            asyncio.run(app.restart_service())

    app.stop_service.assert_awaited_once_with()
    app.start_service.assert_awaited_once_with()
