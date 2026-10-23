from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from telegram_bot.app import TelegramBotApplication
from telegram_bot.config import AppConfig
from telegram_bot.runtime import _parse_linux_network_totals


def test_status_snapshot_keeps_dashboard_history() -> None:
    with TemporaryDirectory() as tmp:
        app = TelegramBotApplication(AppConfig(), Path(tmp) / "config.json")

        first = app.status_snapshot()
        second = app.status_snapshot()

        assert len(second["history"]) >= len(first["history"]) >= 1
        assert {"ts", "cpu", "memory", "upload_bytes", "download_bytes"} <= set(second["history"][-1])


def test_linux_network_totals_skip_loopback() -> None:
    content = """
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000       1    0    0    0     0          0         0 2000       1    0    0    0     0       0          0
  eth0: 3000       2    0    0    0     0          0         0 5000       2    0    0    0     0       0          0
"""

    upload, download = _parse_linux_network_totals(content)

    assert upload == 5000
    assert download == 3000
