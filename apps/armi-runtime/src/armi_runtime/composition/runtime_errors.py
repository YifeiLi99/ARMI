"""Stable failures for Runtime composition and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeViolation(RuntimeError):
    """A safe failure containing no deployment values or raw exceptions."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


__all__ = ("RuntimeViolation",)
