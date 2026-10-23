from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


HandlerStatus = Literal["ignored", "handled", "failed"]


@dataclass
class HandlerResult:
    status: HandlerStatus
    module_id: str
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ignored(cls, module_id: str) -> "HandlerResult":
        return cls(status="ignored", module_id=module_id)

    @classmethod
    def handled(cls, module_id: str, message: str = "", metadata: dict[str, Any] | None = None) -> "HandlerResult":
        return cls(status="handled", module_id=module_id, message=message, metadata=metadata or {})

    @classmethod
    def failed(cls, module_id: str, message: str) -> "HandlerResult":
        return cls(status="failed", module_id=module_id, message=message)
