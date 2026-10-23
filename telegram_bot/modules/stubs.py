from __future__ import annotations

from typing import Any

from telegram_bot.shared.contracts import HandlerResult

from .base import ModuleCard


class BaseStubModule:
    def __init__(self, card: ModuleCard) -> None:
        self.card = card

    async def start(self) -> None:
        self.card.status = "running"

    async def stop(self) -> None:
        self.card.status = "stopped"

    async def handle_message(self, message: Any) -> HandlerResult:
        return HandlerResult.ignored(self.card.id)

    def update_config(self, values: dict[str, Any]) -> None:
        self.card.config.update(values)


class AIReplyModule(BaseStubModule):
    pass


class AIImageModule(BaseStubModule):
    pass
