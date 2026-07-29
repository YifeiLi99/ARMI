"""Safe, stable failures for configuration and secret preflight."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigurationViolation(ValueError):
    """A failure safe to surface without raw values or filesystem details."""

    code: str
    message: str
    field: str | None = None

    def __str__(self) -> str:
        suffix = f" at {self.field}" if self.field is not None else ""
        return f"{self.code}: {self.message}{suffix}"


__all__ = ("ConfigurationViolation",)
