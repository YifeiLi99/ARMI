"""Canonical transport identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self
from uuid import UUID

from ._codec import ContractViolation


@dataclass(frozen=True, slots=True)
class _UuidV7:
    value: UUID

    def __post_init__(self) -> None:
        if type(self.value) is not UUID or self.value.version != 7:
            raise ContractViolation("CON-ID", "expected a UUIDv7")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        if not isinstance(value, str):
            raise ContractViolation("CON-ID", "expected a UUIDv7 string", path=path)
        if value != value.lower():
            raise ContractViolation(
                "CON-ID", "UUID must use lowercase canonical form", path=path
            )
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as error:
            raise ContractViolation("CON-ID", "malformed UUID", path=path) from error
        if str(parsed) != value or parsed.version != 7:
            raise ContractViolation(
                "CON-ID", "expected lowercase canonical UUIDv7", path=path
            )
        return cls(parsed)

    def to_wire(self) -> str:
        return str(self.value)

    def __str__(self) -> str:
        return self.to_wire()


@dataclass(frozen=True, slots=True)
class SubjectId(_UuidV7):
    """Stable subject identity."""


@dataclass(frozen=True, slots=True)
class SceneId(_UuidV7):
    """Stable scene identity."""


@dataclass(frozen=True, slots=True)
class ResultRef(_UuidV7):
    """Durable result reference."""


@dataclass(frozen=True, slots=True)
class ErrorInstanceId(_UuidV7):
    """Reference to private diagnostics for an error occurrence."""


@dataclass(frozen=True, slots=True)
class TraceId:
    """Non-zero 128-bit lowercase hexadecimal trace identifier."""

    value: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9a-f]{32}", self.value, flags=re.ASCII) is None
            or self.value == "0" * 32
        ):
            raise ContractViolation(
                "CON-TRACE", "expected a non-zero 32-character lowercase hex value"
            )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        if not isinstance(value, str):
            raise ContractViolation("CON-TRACE", "expected a trace string", path=path)
        try:
            return cls(value)
        except ContractViolation as error:
            raise ContractViolation(error.code, error.message, path=path) from None

    def to_wire(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value
