"""Technology-neutral T-05 policy decision and effect ledger contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, Instant


class PolicyDecisionOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNAVAILABLE = "unavailable"


class EffectStatus(StrEnum):
    REGISTERED = "registered"
    CANCELLED = "cancelled"


class EffectVerificationStatus(StrEnum):
    NOT_STARTED = "not_started"


@dataclass(frozen=True, slots=True)
class PolicyDecisionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectRegistrationResult:
    effect_id: EffectId
    policy_decision_id: PolicyDecisionId
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registration_digest: Digest
    registered_at: Instant


@dataclass(frozen=True, slots=True)
class EffectView:
    effect_id: EffectId
    root_operation_ref: UUID
    effect_kind: str
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registered_at: Instant
    cancelled_at: Instant | None = None

    def __post_init__(self) -> None:
        _uuid7(self.root_operation_ref)
        if self.effect_kind != "creator_response":
            raise EffectViolation("CON-EFFECT-KIND")
        if (self.status is EffectStatus.CANCELLED) != (self.cancelled_at is not None):
            raise EffectViolation("CON-EFFECT-STATE")


class EffectViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(
                r"(?:CON-)?EFFECT-[A-Z0-9-]+|SCOPE-EFFECT-NOT-VISIBLE", code
            )
            is None
        ):
            raise ValueError("effect violation code is invalid")
        self.code = code
        super().__init__("effect ledger operation failed")

    def __str__(self) -> str:
        return f"{self.code}: effect ledger operation failed"


@runtime_checkable
class EffectLedgerPort(Protocol):
    async def register_once(self) -> bool: ...

    async def get_effect(
        self, effect_id: EffectId, *, creator_party_id: UUID
    ) -> EffectView: ...


def _uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise EffectViolation("CON-EFFECT-ID")


__all__ = (
    "EffectId",
    "EffectLedgerPort",
    "EffectRegistrationResult",
    "EffectStatus",
    "EffectVerificationStatus",
    "EffectView",
    "EffectViolation",
    "PolicyDecisionId",
    "PolicyDecisionOutcome",
)
