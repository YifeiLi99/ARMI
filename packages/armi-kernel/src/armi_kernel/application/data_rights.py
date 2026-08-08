"""Commands and projections for requester-scoped local data rights."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId

from .other_human_input import OtherHumanPartyKey


class DataRightsRequesterKind(StrEnum):
    CREATOR = "creator"
    OTHER_HUMAN = "other_human"


class DataRightsOrderKind(StrEnum):
    STOP_CONTACT = "stop_contact"
    STOP_USE = "stop_use"
    DELETE_RELATED = "delete_related"


class DataRightsScopeKind(StrEnum):
    PARTY_CONTACT = "party_contact"
    PARTY_LOCAL_DATA = "party_local_data"


class DataRightsExecutionStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL = "partial"


class DataRightsViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("DATA-RIGHTS-"):
            raise ValueError("data rights violation code is invalid")
        self.code = code
        super().__init__("data rights operation failed")


@dataclass(frozen=True, slots=True)
class DataRightsOrderCommand:
    order_kind: DataRightsOrderKind
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.order_kind) is not DataRightsOrderKind
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
        ):
            raise DataRightsViolation("DATA-RIGHTS-COMMAND")


@dataclass(frozen=True, slots=True)
class DataRightsOrderResult:
    order_id: UUID
    requester_party_id: UUID
    requester_kind: DataRightsRequesterKind
    order_kind: DataRightsOrderKind
    scope_kind: DataRightsScopeKind
    scope_party_id: UUID
    status: str
    execution_status: DataRightsExecutionStatus
    request_digest: Digest
    effective_at: Instant
    completed_at: Instant | None
    newly_created: bool

    def __post_init__(self) -> None:
        uuids = (self.order_id, self.requester_party_id, self.scope_party_id)
        if (
            any(type(value) is not UUID or value.version != 7 for value in uuids)
            or self.requester_party_id != self.scope_party_id
            or type(self.requester_kind) is not DataRightsRequesterKind
            or type(self.order_kind) is not DataRightsOrderKind
            or type(self.scope_kind) is not DataRightsScopeKind
            or self.status != "effective"
            or type(self.execution_status) is not DataRightsExecutionStatus
            or type(self.request_digest) is not Digest
            or type(self.effective_at) is not Instant
            or type(self.newly_created) is not bool
            or (
                self.order_kind is DataRightsOrderKind.STOP_CONTACT
                and self.scope_kind is not DataRightsScopeKind.PARTY_CONTACT
            )
            or (
                self.order_kind is not DataRightsOrderKind.STOP_CONTACT
                and self.scope_kind is not DataRightsScopeKind.PARTY_LOCAL_DATA
            )
            or (
                self.order_kind is DataRightsOrderKind.DELETE_RELATED
                and self.execution_status is DataRightsExecutionStatus.NOT_REQUIRED
            )
            or (
                self.order_kind is not DataRightsOrderKind.DELETE_RELATED
                and self.execution_status is not DataRightsExecutionStatus.NOT_REQUIRED
            )
            or (
                self.execution_status
                in {
                    DataRightsExecutionStatus.COMPLETED,
                    DataRightsExecutionStatus.PARTIAL,
                }
            )
            != (self.completed_at is not None)
        ):
            raise DataRightsViolation("DATA-RIGHTS-RESULT")


@runtime_checkable
class DataRightsOrderPort(Protocol):
    async def request_creator(
        self, command: DataRightsOrderCommand
    ) -> DataRightsOrderResult: ...

    async def request_other_human(
        self,
        party_key: OtherHumanPartyKey,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult: ...

    async def get_creator(self, order_id: UUID) -> DataRightsOrderResult | None: ...

    async def get_other_human(
        self,
        party_key: OtherHumanPartyKey,
        order_id: UUID,
    ) -> DataRightsOrderResult | None: ...


__all__ = (
    "DataRightsExecutionStatus",
    "DataRightsOrderCommand",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderResult",
    "DataRightsRequesterKind",
    "DataRightsScopeKind",
    "DataRightsViolation",
)
