"""Mood invariants independent of persistence and Runtime."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import CandidateMoodDraft, MoodViolation

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


def validate_state(value: dict[str, object]) -> None:
    if set(value) != {"schema_version", "emotions", "mood"}:
        raise MoodViolation("MOOD-STATE")
    if value["schema_version"] != "armi.mood.v1":
        raise MoodViolation("MOOD-STATE")
    emotions = value["emotions"]
    mood = value["mood"]
    if type(emotions) is not list:
        raise MoodViolation("MOOD-STATE")
    emotion_items = cast(list[object], emotions)
    if len(emotion_items) > 16 or any(
        type(item) is not str or not item.strip() or "\x00" in item or len(item) > 512
        for item in emotion_items
    ):
        raise MoodViolation("MOOD-STATE")
    if mood is not None and (
        type(mood) is not str or not mood.strip() or "\x00" in mood or len(mood) > 128
    ):
        raise MoodViolation("MOOD-STATE")


def validate_candidate(value: CandidateMoodDraft) -> None:
    if (
        _REF.fullmatch(value.proposal_ref) is None
        or _GROUP.fullmatch(value.atomic_group_ref) is None
        or type(value.basis_ordinals) is not tuple
        or not 1 <= len(value.basis_ordinals) <= 8
        or any(
            type(item) is not int or not 1 <= item <= 999
            for item in value.basis_ordinals
        )
        or len(value.basis_ordinals) != len(set(value.basis_ordinals))
        or type(value.fact_class) is not CandidateFactClass
        or type(value.expected_version) is not int
        or value.expected_version <= 0
        or type(value.canonical_next_state) is not bytes
        or not value.canonical_next_state
    ):
        raise MoodViolation("MOOD-CANDIDATE")
    try:
        raw = json.loads(value.canonical_next_state)
        if (
            type(raw) is not dict
            or rfc8785.dumps(cast(Any, raw)) != value.canonical_next_state
        ):
            raise ValueError
        validate_state(cast(dict[str, object], raw))
    except UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError:
        raise MoodViolation("MOOD-CANDIDATE") from None


__all__ = ("validate_candidate", "validate_state")
