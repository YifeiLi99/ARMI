"""Stable public error descriptors."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from ._codec import (
    FrozenJson,
    optional_details,
    require_exact_fields,
    require_mapping,
    thaw_json,
)
from .ids import ErrorInstanceId


class ErrorCategory(StrEnum):
    INPUT = "input"
    AUTH = "auth"
    SCOPE = "scope"
    STATE = "state"
    CONFLICT = "conflict"
    IDEMPOTENCY = "idempotency"
    POLICY = "policy"
    CAPABILITY = "capability"
    DEPENDENCY = "dependency"
    EFFECT = "effect"
    INTEGRITY = "integrity"
    ADMIN = "admin"
    INTERNAL = "internal"


_CATEGORY_PREFIX = {
    ErrorCategory.INPUT: "INPUT_",
    ErrorCategory.AUTH: "AUTH_",
    ErrorCategory.SCOPE: "SCOPE_",
    ErrorCategory.STATE: "STATE_",
    ErrorCategory.CONFLICT: "CONFLICT_",
    ErrorCategory.IDEMPOTENCY: "IDEMPOTENCY_",
    ErrorCategory.POLICY: "POLICY_",
    ErrorCategory.CAPABILITY: "CAPABILITY_",
    ErrorCategory.DEPENDENCY: "DEPENDENCY_",
    ErrorCategory.EFFECT: "EFFECT_",
    ErrorCategory.INTEGRITY: "INTEGRITY_",
    ErrorCategory.ADMIN: "ADMIN_",
    ErrorCategory.INTERNAL: "INTERNAL_",
}


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    category: ErrorCategory
    code: str
    details: Mapping[str, FrozenJson] | None = None
    error_instance_id: ErrorInstanceId | None = None

    def __post_init__(self) -> None:
        if type(self.category) is not ErrorCategory:
            raise TypeError("category must be ErrorCategory")
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", self.code) is None:
            from ._codec import ContractViolation

            raise ContractViolation("CON-ERROR", "error code is not canonical")
        if not self.code.startswith(_CATEGORY_PREFIX[self.category]):
            from ._codec import ContractViolation

            raise ContractViolation(
                "CON-ERROR", "error code prefix does not match category"
            )
        if self.details is not None:
            object.__setattr__(
                self, "details", optional_details(self.details, path="$.details")
            )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        from ._codec import ContractViolation

        wire = require_mapping(value, path=path)
        require_exact_fields(
            wire,
            required=frozenset({"category", "code"}),
            optional=frozenset({"details", "error_instance_id"}),
            path=path,
        )
        raw_category = wire["category"]
        if not isinstance(raw_category, str):
            raise ContractViolation(
                "CON-ERROR", "category must be a string", path=f"{path}.category"
            )
        try:
            category = ErrorCategory(raw_category)
        except ValueError as error:
            raise ContractViolation(
                "CON-ERROR", "unknown error category", path=f"{path}.category"
            ) from error
        code = wire["code"]
        if not isinstance(code, str):
            raise ContractViolation(
                "CON-ERROR", "code must be a string", path=f"{path}.code"
            )
        details = (
            optional_details(wire["details"], path=f"{path}.details")
            if "details" in wire
            else None
        )
        instance = (
            ErrorInstanceId.from_wire(
                wire["error_instance_id"], path=f"{path}.error_instance_id"
            )
            if "error_instance_id" in wire
            else None
        )
        try:
            return cls(category, code, details, instance)
        except ContractViolation as error:
            raise ContractViolation(error.code, error.message, path=path) from None

    def to_wire(self) -> dict[str, object]:
        wire: dict[str, object] = {
            "category": self.category.value,
            "code": self.code,
        }
        if self.details is not None:
            wire["details"] = thaw_json(self.details)
        if self.error_instance_id is not None:
            wire["error_instance_id"] = self.error_instance_id.to_wire()
        return wire
