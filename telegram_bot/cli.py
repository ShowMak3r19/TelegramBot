from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .app import TelegramBotApplication
from .config import AppConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telebot service")
    parser.add_argument(
        "--config",
        default=os.getenv("TGBOT_CONFIG", "config.json"),
        help="Path to runtime config JSON. Defaults to TGBOT_CONFIG or ./config.json.",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create a config file from defaults if it does not exist.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if args.init_config:
        AppConfig.ensure_file(config_path)
        print(f"Config ready: {config_path}")
        return 0

    config = AppConfig.load(config_path)
    app = TelegramBotApplication(config=config, config_path=config_path)
    await app.run_forever()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))
