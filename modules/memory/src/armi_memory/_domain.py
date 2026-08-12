"""Subjective-memory lifecycle rules."""

from __future__ import annotations

from .api import (
    CandidateMemoryRevisionDraft,
    MemoryAccessibility,
    MemoryRevisionKind,
    MemoryViolation,
)


def validate_transition(
    current: MemoryAccessibility, proposed: CandidateMemoryRevisionDraft
) -> None:
    allowed = {
        MemoryAccessibility.AVAILABLE: {
            MemoryRevisionKind.RECALLED,
            MemoryRevisionKind.FADED,
            MemoryRevisionKind.FORGOTTEN,
            MemoryRevisionKind.REINTERPRETED,
        },
        MemoryAccessibility.FADED: {
            MemoryRevisionKind.RECALLED,
            MemoryRevisionKind.FORGOTTEN,
            MemoryRevisionKind.REINTERPRETED,
        },
    }
    if proposed.revision_kind not in allowed.get(current, set()):
        raise MemoryViolation("MEMORY-TRANSITION")
    if (
        proposed.revision_kind is MemoryRevisionKind.REINTERPRETED
        and proposed.accessibility is not current
    ):
        raise MemoryViolation("MEMORY-TRANSITION")


__all__ = ("validate_transition",)
