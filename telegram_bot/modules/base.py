from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from telegram_bot.shared.contracts import HandlerResult


@dataclass
class ModuleCard:
    id: str
    name: str
    description: str
    category: str
    enabled: bool = False
    status: str = "idle"
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


class FeatureModule(Protocol):
    card: ModuleCard

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def handle_message(self, message: Any) -> HandlerResult:
        ...

    def update_config(self, values: dict[str, Any]) -> None:
        ...
