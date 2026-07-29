"""Validated scalar values used by transport envelopes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

from ._codec import ContractViolation, require_ascii_token

_INSTANT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d{1,6})?"
    r"(?:Z|[+-](?!00:00)\d{2}:\d{2})",
    flags=re.ASCII,
)
_CURSOR_PATTERN = re.compile(r"v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class Digest:
    """A lowercase SHA-256 digest with an explicit algorithm prefix."""

    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.value) is None:
            raise ContractViolation("CON-DIGEST", "expected sha256:<64 lowercase hex>")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        if not isinstance(value, str):
            raise ContractViolation("CON-DIGEST", "expected a digest string", path=path)
        try:
            return cls(value)
        except ContractViolation as error:
            raise ContractViolation(error.code, error.message, path=path) from None

    @classmethod
    def from_bytes(cls, value: bytes) -> Self:
        if type(value) is not bytes:
            raise ContractViolation("CON-TYPE", "digest input must be raw bytes")
        return cls(f"sha256:{hashlib.sha256(value).hexdigest()}")

    def to_wire(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Instant:
    """UTC instant serialized with exactly six fractional digits and ``Z``."""

    value: datetime

    def __post_init__(self) -> None:
        if type(self.value) is not datetime or self.value.tzinfo is None:
            raise ContractViolation("CON-TIME", "instant must be timezone-aware")
        if self.value.utcoffset() != UTC.utcoffset(self.value):
            raise ContractViolation("CON-TIME", "instant must be normalized to UTC")

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        if not isinstance(value, str) or _INSTANT_PATTERN.fullmatch(value) is None:
            raise ContractViolation(
                "CON-TIME",
                "expected RFC 3339 time with Z or a non-unknown numeric offset",
                path=path,
            )
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise ContractViolation(
                "CON-TIME", "malformed instant", path=path
            ) from error
        return cls(parsed.astimezone(UTC))

    def to_wire(self) -> str:
        return self.value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def __str__(self) -> str:
        return self.to_wire()


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        require_ascii_token(self.value, path="$", maximum=128, lowercase=False)

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        token = require_ascii_token(value, path=path, maximum=128, lowercase=False)
        return cls(token)

    def to_wire(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Purpose:
    value: str

    def __post_init__(self) -> None:
        require_ascii_token(self.value, path="$", maximum=64, lowercase=True)

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        return cls(require_ascii_token(value, path=path, maximum=64, lowercase=True))

    def to_wire(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OpaqueCursor:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) > 2048 or _CURSOR_PATTERN.fullmatch(self.value) is None:
            raise ContractViolation(
                "CON-PAGE",
                "cursor must have bounded v1.<payload>.<signature> base64url shape",
            )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        if not isinstance(value, str):
            raise ContractViolation("CON-PAGE", "expected a cursor string", path=path)
        try:
            return cls(value)
        except ContractViolation as error:
            raise ContractViolation(error.code, error.message, path=path) from None

    def to_wire(self) -> str:
        return self.value
