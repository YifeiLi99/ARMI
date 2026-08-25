"""Technology-neutral custody for slow operations crossing authority boundaries."""

from __future__ import annotations

import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Instant


class ExecutionCustodyScopeKind(StrEnum):
    RUNTIME_AUTHORITY = "runtime_authority"
    DATA_RIGHTS_PARTY = "data_rights_party"
    OUTREACH_SCENE = "outreach_scene"


class ExecutionCustodyMode(StrEnum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


_ORDER = {
    ExecutionCustodyScopeKind.RUNTIME_AUTHORITY: 0,
    ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY: 1,
    ExecutionCustodyScopeKind.OUTREACH_SCENE: 2,
}


@dataclass(frozen=True, slots=True)
class ExecutionCustodyScope:
    kind: ExecutionCustodyScopeKind
    reference: UUID

    def __post_init__(self) -> None:
        if (
            type(self.kind) is not ExecutionCustodyScopeKind
            or type(self.reference) is not UUID
            or self.reference.version != 7
        ):
            raise ExecutionCustodyViolation("CUSTODY-SCOPE")

    @property
    def lock_name(self) -> str:
        return f"armi.execution-custody:{self.kind.value}:{self.reference}"


@dataclass(frozen=True, slots=True)
class ExecutionCustodyRequest:
    scope: ExecutionCustodyScope
    mode: ExecutionCustodyMode

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not ExecutionCustodyScope
            or type(self.mode) is not ExecutionCustodyMode
        ):
            raise ExecutionCustodyViolation("CUSTODY-REQUEST")


@dataclass(frozen=True, slots=True)
class ExecutionCustodyPermit:
    requests: tuple[ExecutionCustodyRequest, ...]

    def __post_init__(self) -> None:
        if not self.requests or any(
            type(item) is not ExecutionCustodyRequest for item in self.requests
        ):
            raise ExecutionCustodyViolation("CUSTODY-REQUEST")
        ordered = tuple(
            sorted(
                self.requests,
                key=lambda item: (_ORDER[item.scope.kind], item.scope.reference.int),
            )
        )
        if ordered != self.requests or len({item.scope for item in ordered}) != len(
            ordered
        ):
            raise ExecutionCustodyViolation("CUSTODY-ORDER")


class ExecutionCustodyViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or re.fullmatch(r"CUSTODY-[A-Z0-9-]+", code) is None:
            raise ValueError("execution custody violation code is invalid")
        self.code = code
        super().__init__("execution custody operation failed")


def ordered_custody_requests(
    *requests: ExecutionCustodyRequest,
) -> tuple[ExecutionCustodyRequest, ...]:
    ordered = tuple(
        sorted(
            requests,
            key=lambda item: (_ORDER[item.scope.kind], item.scope.reference.int),
        )
    )
    ExecutionCustodyPermit(ordered)
    return ordered


@runtime_checkable
class ExecutionCustodyPort(Protocol):
    def hold(
        self,
        requests: tuple[ExecutionCustodyRequest, ...],
        *,
        deadline_at: Instant | None,
    ) -> AbstractAsyncContextManager[ExecutionCustodyPermit]: ...


__all__ = (
    "ExecutionCustodyMode",
    "ExecutionCustodyPermit",
    "ExecutionCustodyPort",
    "ExecutionCustodyRequest",
    "ExecutionCustodyScope",
    "ExecutionCustodyScopeKind",
    "ExecutionCustodyViolation",
    "ordered_custody_requests",
)
