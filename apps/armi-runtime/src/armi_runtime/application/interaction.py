"""One application dispatch boundary for authenticated interaction clients."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from armi_local_control.binding import AuthenticatedDelegate


@dataclass(frozen=True, slots=True)
class InteractionOperation:
    name: str
    group: str
    action: str
    mutating: bool
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class InteractionInvocation:
    operation: str
    arguments: Mapping[str, object]
    caller: AuthenticatedDelegate


@dataclass(frozen=True, slots=True)
class InteractionResult:
    status: Literal["returned", "rejected", "unavailable"]
    payload: Mapping[str, object]
    status_code: int = 200
    content: bytes | None = None
    media_type: str | None = None


type InteractionHandler = Callable[
    [InteractionInvocation], Awaitable[InteractionResult]
]


class InteractionApplication:
    """Authorize once and dispatch the same named use cases for CLI and MCP."""

    def __init__(self) -> None:
        self._operations: dict[str, InteractionOperation] = {}
        self._handlers: dict[str, InteractionHandler] = {}

    def register(
        self, operation: InteractionOperation, handler: InteractionHandler
    ) -> None:
        if operation.name in self._operations:
            raise ValueError("INTERACTION-OPERATION-DUPLICATE")
        self._operations[operation.name] = operation
        self._handlers[operation.name] = handler

    def operations(self) -> tuple[InteractionOperation, ...]:
        return tuple(self._operations.values())

    async def invoke(self, invocation: InteractionInvocation) -> InteractionResult:
        operation = self._operations.get(invocation.operation)
        if operation is None:
            return InteractionResult(
                "rejected", {"error_code": "INTERACTION-OPERATION-UNKNOWN"}, 400
            )
        required = "interaction.write" if operation.mutating else "interaction.read"
        if required not in invocation.caller.scopes:
            return InteractionResult(
                "rejected", {"error_code": "INTERACTION-SCOPE-REQUIRED"}, 403
            )
        return await self._handlers[operation.name](invocation)
