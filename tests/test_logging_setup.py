from __future__ import annotations

import logging
from pathlib import Path

from telegram_bot.config import LogConfig
from telegram_bot.logging_setup import configure_logging, list_log_files, read_log_tail, shutdown_logging


def test_log_rotation_keeps_configured_files(tmp_path: Path) -> None:
    config = LogConfig(dir="logs", file_name="bot.log", max_bytes=200, max_files=5)
    configure_logging(config, tmp_path)

    for index in range(120):
        logging.info("line %s %s", index, "x" * 40)

    files = list_log_files(config, tmp_path)
    assert len(files) <= 5
    assert any(item["name"] == "bot.log" for item in files)
    assert "line" in read_log_tail(config, tmp_path, "bot.log", 20)
    shutdown_logging()
