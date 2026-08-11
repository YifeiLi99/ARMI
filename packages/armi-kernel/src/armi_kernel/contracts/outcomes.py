"""The eight frozen transport outcome variants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Self, TypedDict

from ._codec import (
    CONTRACT_VERSION,
    MAX_SAFE_INTEGER,
    ContractViolation,
    FrozenJson,
    optional_details,
    require_ascii_token,
    require_contract_version,
    require_exact_fields,
    require_mapping,
    require_string,
    thaw_json,
)
from .errors import ErrorDescriptor
from .ids import ResultRef, TraceId
from .values import Instant

_COMMON_REQUIRED = frozenset(
    {"contract_version", "status", "trace_id", "occurred_at", "message"}
)
_COMMON_OPTIONAL = frozenset({"details"})


@dataclass(frozen=True, slots=True)
class _CommonOutcome:
    trace_id: TraceId
    occurred_at: Instant
    message: str
    details: Mapping[str, FrozenJson] | None


class _CommonArguments(TypedDict):
    trace_id: TraceId
    occurred_at: Instant
    message: str
    details: Mapping[str, FrozenJson] | None


def _common_arguments(common: _CommonOutcome) -> _CommonArguments:
    return {
        "trace_id": common.trace_id,
        "occurred_at": common.occurred_at,
        "message": common.message,
        "details": common.details,
    }


def _decode_common(
    value: object,
    *,
    status: str,
    variant_required: frozenset[str],
    variant_optional: frozenset[str] = frozenset(),
    path: str,
) -> tuple[Mapping[str, object], _CommonOutcome]:
    wire = require_mapping(value, path=path)
    require_exact_fields(
        wire,
        required=_COMMON_REQUIRED | variant_required,
        optional=_COMMON_OPTIONAL | variant_optional,
        path=path,
    )
    require_contract_version(wire["contract_version"], path=f"{path}.contract_version")
    if wire["status"] != status or not isinstance(wire["status"], str):
        raise ContractViolation(
            "CON-OUTCOME",
            f"status must be exactly {status!r}",
            path=f"{path}.status",
        )
    details = (
        optional_details(wire["details"], path=f"{path}.details")
        if "details" in wire
        else None
    )
    return wire, _CommonOutcome(
        trace_id=TraceId.from_wire(wire["trace_id"], path=f"{path}.trace_id"),
        occurred_at=Instant.from_wire(wire["occurred_at"], path=f"{path}.occurred_at"),
        message=require_string(wire["message"], path=f"{path}.message"),
        details=details,
    )


def _common_wire(outcome: _OutcomeBase) -> dict[str, object]:
    wire: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "status": outcome.status,
        "trace_id": outcome.trace_id.to_wire(),
        "occurred_at": outcome.occurred_at.to_wire(),
        "message": outcome.message,
    }
    if outcome.details is not None:
        wire["details"] = thaw_json(outcome.details)
    return wire


@dataclass(frozen=True, slots=True, kw_only=True)
class _OutcomeBase:
    trace_id: TraceId
    occurred_at: Instant
    message: str
    details: Mapping[str, FrozenJson] | None = None
    status: ClassVar[str]

    def __post_init__(self) -> None:
        require_string(self.message, path="$.message")
        if self.details is not None:
            object.__setattr__(
                self, "details", optional_details(self.details, path="$.details")
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedOutcome(_OutcomeBase):
    status: ClassVar[str] = "accepted"
    result_ref: ResultRef
    custodian: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require_ascii_token(
            self.custodian, path="$.custodian", maximum=64, lowercase=True
        )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"result_ref", "custodian"}),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            result_ref=ResultRef.from_wire(
                wire["result_ref"], path=f"{path}.result_ref"
            ),
            custodian=require_ascii_token(
                wire["custodian"],
                path=f"{path}.custodian",
                maximum=64,
                lowercase=True,
            ),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {
            "result_ref": self.result_ref.to_wire(),
            "custodian": self.custodian,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AppliedOutcome(_OutcomeBase):
    status: ClassVar[str] = "applied"
    result_ref: ResultRef
    state_version: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            type(self.state_version) is not int
            or not 0 <= self.state_version <= MAX_SAFE_INTEGER
        ):
            raise ContractViolation(
                "CON-OUTCOME", "state_version must be a non-negative safe integer"
            )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"result_ref", "state_version"}),
            path=path,
        )
        state_version = wire["state_version"]
        if (
            isinstance(state_version, bool)
            or not isinstance(state_version, int)
            or not 0 <= state_version <= MAX_SAFE_INTEGER
        ):
            raise ContractViolation(
                "CON-OUTCOME",
                "state_version must be a non-negative safe integer",
                path=f"{path}.state_version",
            )
        return cls(
            **_common_arguments(common),
            result_ref=ResultRef.from_wire(
                wire["result_ref"], path=f"{path}.result_ref"
            ),
            state_version=state_version,
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {
            "result_ref": self.result_ref.to_wire(),
            "state_version": self.state_version,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class WaitingOutcome(_OutcomeBase):
    status: ClassVar[str] = "waiting"
    result_ref: ResultRef
    waiting_for: str
    resume_condition: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require_ascii_token(
            self.waiting_for, path="$.waiting_for", maximum=64, lowercase=True
        )
        require_string(self.resume_condition, path="$.resume_condition")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset(
                {"result_ref", "waiting_for", "resume_condition"}
            ),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            result_ref=ResultRef.from_wire(
                wire["result_ref"], path=f"{path}.result_ref"
            ),
            waiting_for=require_ascii_token(
                wire["waiting_for"],
                path=f"{path}.waiting_for",
                maximum=64,
                lowercase=True,
            ),
            resume_condition=require_string(
                wire["resume_condition"], path=f"{path}.resume_condition"
            ),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {
            "result_ref": self.result_ref.to_wire(),
            "waiting_for": self.waiting_for,
            "resume_condition": self.resume_condition,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectedOutcome(_OutcomeBase):
    status: ClassVar[str] = "rejected"
    error: ErrorDescriptor

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"error"}),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            error=ErrorDescriptor.from_wire(wire["error"], path=f"{path}.error"),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {"error": self.error.to_wire()}


@dataclass(frozen=True, slots=True, kw_only=True)
class UnavailableOutcome(_OutcomeBase):
    status: ClassVar[str] = "unavailable"
    error: ErrorDescriptor
    recovery_hint: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.recovery_hint is not None:
            require_string(self.recovery_hint, path="$.recovery_hint")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"error"}),
            variant_optional=frozenset({"recovery_hint"}),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            error=ErrorDescriptor.from_wire(wire["error"], path=f"{path}.error"),
            recovery_hint=(
                require_string(wire["recovery_hint"], path=f"{path}.recovery_hint")
                if "recovery_hint" in wire
                else None
            ),
        )

    def to_wire(self) -> dict[str, object]:
        wire = _common_wire(self) | {"error": self.error.to_wire()}
        if self.recovery_hint is not None:
            wire["recovery_hint"] = self.recovery_hint
        return wire


@dataclass(frozen=True, slots=True, kw_only=True)
class FailedOutcome(_OutcomeBase):
    status: ClassVar[str] = "failed"
    error: ErrorDescriptor

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"error"}),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            error=ErrorDescriptor.from_wire(wire["error"], path=f"{path}.error"),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {"error": self.error.to_wire()}


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownOutcome(_OutcomeBase):
    status: ClassVar[str] = "unknown"
    result_ref: ResultRef
    custodian: str
    verification_action: str

    def __post_init__(self) -> None:
        super().__post_init__()
        require_ascii_token(
            self.custodian, path="$.custodian", maximum=64, lowercase=True
        )
        require_string(self.verification_action, path="$.verification_action")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset(
                {"result_ref", "custodian", "verification_action"}
            ),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            result_ref=ResultRef.from_wire(
                wire["result_ref"], path=f"{path}.result_ref"
            ),
            custodian=require_ascii_token(
                wire["custodian"],
                path=f"{path}.custodian",
                maximum=64,
                lowercase=True,
            ),
            verification_action=require_string(
                wire["verification_action"],
                path=f"{path}.verification_action",
            ),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {
            "result_ref": self.result_ref.to_wire(),
            "custodian": self.custodian,
            "verification_action": self.verification_action,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedOutcome(_OutcomeBase):
    status: ClassVar[str] = "completed"
    result_ref: ResultRef

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire, common = _decode_common(
            value,
            status=cls.status,
            variant_required=frozenset({"result_ref"}),
            path=path,
        )
        return cls(
            **_common_arguments(common),
            result_ref=ResultRef.from_wire(
                wire["result_ref"], path=f"{path}.result_ref"
            ),
        )

    def to_wire(self) -> dict[str, object]:
        return _common_wire(self) | {
            "result_ref": self.result_ref.to_wire(),
        }


type Outcome = (
    AcceptedOutcome
    | AppliedOutcome
    | WaitingOutcome
    | RejectedOutcome
    | UnavailableOutcome
    | FailedOutcome
    | UnknownOutcome
    | CompletedOutcome
)
