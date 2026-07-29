"""Technology-neutral credential acquisition contracts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self, TypeVar, runtime_checkable

_SCHEME = re.compile(r"^[a-z][a-z0-9-]{1,31}$", re.ASCII)
_PURPOSE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_MAX_LOCATOR_TARGET_LENGTH = 2048
_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class CredentialLocator:
    """A secret reference identity; never the referenced secret value."""

    scheme: str
    target: str

    def __post_init__(self) -> None:
        if _SCHEME.fullmatch(self.scheme) is None:
            raise ValueError("credential locator scheme is invalid")
        if (
            not self.target
            or len(self.target) > _MAX_LOCATOR_TARGET_LENGTH
            or any(ord(character) < 0x20 for character in self.target)
        ):
            raise ValueError("credential locator target is invalid")

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse the bounded ``scheme:target`` wire shape."""

        if ":" not in value:
            raise ValueError("credential locator is invalid")
        scheme, target = value.split(":", 1)
        return cls(scheme=scheme, target=target)

    def identity(self) -> str:
        """Return the identity used by effective-config digesting."""

        return f"{self.scheme}:{self.target}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(scheme={self.scheme!r}, target=<redacted>)"

    def __str__(self) -> str:
        return f"{self.scheme}:<redacted>"


@dataclass(frozen=True, slots=True)
class CredentialPurpose:
    """A bounded caller-supplied reason for resolving one credential."""

    value: str

    def __post_init__(self) -> None:
        if _PURPOSE.fullmatch(self.value) is None:
            raise ValueError("credential purpose is invalid")

    def __str__(self) -> str:
        return self.value


@runtime_checkable
class SecretHandle(Protocol):
    """A short-lived, non-serializable secret access handle."""

    @property
    def closed(self) -> bool:
        """Whether the handle can no longer expose its buffer."""
        ...

    def consume(self, operation: Callable[[memoryview], _ResultT]) -> _ResultT:
        """Expose a read-only view only for the duration of ``operation``."""
        ...

    def close(self) -> None:
        """Clear the backing buffer and make the handle unusable."""
        ...

    def __enter__(self) -> Self:
        """Enter a bounded secret lifetime."""
        ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the handle at the end of the bounded lifetime."""
        ...


@runtime_checkable
class CredentialPort(Protocol):
    """Resolve an approved locator for one explicit purpose."""

    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        """Return a fresh handle or fail without exposing the secret."""
        ...


__all__ = (
    "CredentialLocator",
    "CredentialPort",
    "CredentialPurpose",
    "SecretHandle",
)
