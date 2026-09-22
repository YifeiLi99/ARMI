"""Public event-processing boundary; callers never supply a target mood."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from armi_kernel.application import ProviderCallReceipt, WorkLease
from armi_runtime_foundation import PostgreSQLTransaction

from ._psychology import Affect, MoodDynamics
from ._questions import EvaluatedAppraisal


@dataclass(frozen=True)
class MoodEvent:
    event_key: str
    subject_id: UUID
    episode_id: UUID
    source_ref: UUID
    source_version: int
    occurred_at: datetime
    summary: str


@dataclass(frozen=True)
class MoodAssessment:
    assessment_id: UUID
    event: MoodEvent
    status: str
    mood_version: int
    state: MoodDynamics


@dataclass(frozen=True)
class MoodView:
    current_revision_id: UUID
    version: int
    as_of: datetime
    current: Affect
    state: MoodDynamics
    evaluation_status: str
    assessment_id: UUID | None
    failure_code: str | None
    unknown: tuple[str, ...] = ()


class MoodAppraiserPort(Protocol):
    async def evaluate(
        self,
        *,
        assessment: MoodAssessment,
        context: dict[str, Any],
    ) -> EvaluatedAppraisal: ...


class MoodEvaluationPort(Protocol):
    async def evaluate(
        self,
        *,
        event: MoodEvent,
        lease: WorkLease,
        compiled_context: bytes,
    ) -> None: ...


class MoodEventStorePort(Protocol):
    async def record_provider_call(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        receipt: ProviderCallReceipt,
    ) -> None: ...

    async def begin(
        self,
        transaction: PostgreSQLTransaction,
        *,
        event: MoodEvent,
        context: dict[str, Any],
    ) -> MoodAssessment: ...

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment: MoodAssessment,
        result: EvaluatedAppraisal,
        at: datetime,
    ) -> bool: ...

    async def fail(
        self,
        transaction: PostgreSQLTransaction,
        *,
        assessment_id: UUID,
        code: str,
        interrupted: bool = False,
    ) -> None: ...
