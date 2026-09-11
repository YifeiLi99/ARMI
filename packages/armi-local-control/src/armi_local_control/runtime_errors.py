"""Stable failures for Runtime composition and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeViolation(RuntimeError):
    """Safe failure; traceback must remain writable for context managers."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


__all__ = ("RuntimeViolation",)
