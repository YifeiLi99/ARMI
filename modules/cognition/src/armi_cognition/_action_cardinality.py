"""One action-cardinality rule used by model, validation and persisted codecs."""

from __future__ import annotations

from collections.abc import Iterable


def validate_action_kinds(kinds: Iterable[str]) -> None:
    values = tuple(kinds)
    conversational = tuple(value for value in values if value != "codex_delegation")
    delegated = tuple(value for value in values if value == "codex_delegation")
    if len(values) > 2 or len(conversational) > 1 or len(delegated) > 1:
        raise ValueError("CANDIDATE-ACTION-CARDINALITY")


__all__ = ("validate_action_kinds",)
