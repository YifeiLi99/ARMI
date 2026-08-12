"""Subject-state invariants independent of persistence and Runtime."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import CandidateSubjectStateDraft, SubjectStateKind, SubjectStateViolation

_REF = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


def validate_candidate(value: CandidateSubjectStateDraft) -> None:
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
        or type(value.kind) is not SubjectStateKind
        or type(value.expected_version) is not int
        or value.expected_version <= 0
        or type(value.canonical_next_state) is not bytes
        or not value.canonical_next_state
    ):
        raise SubjectStateViolation("SUBJECT-STATE-CANDIDATE")
    try:
        raw = json.loads(value.canonical_next_state)
        if (
            type(raw) is not dict
            or rfc8785.dumps(cast(Any, raw)) != value.canonical_next_state
        ):
            raise ValueError
        validate_state(value.kind, cast(dict[str, object], raw))
    except UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError:
        raise SubjectStateViolation("SUBJECT-STATE-CANDIDATE") from None


def validate_state(kind: SubjectStateKind, value: dict[str, object]) -> None:
    if kind is SubjectStateKind.SELF:
        _self(value)
    elif kind is SubjectStateKind.MIND:
        _mind(value)
    else:
        _life_mode(value)


def _text_or_none(value: object, maximum: int) -> bool:
    return value is None or (
        type(value) is str
        and bool(value.strip())
        and "\x00" not in value
        and len(value) <= maximum
    )


def _texts(value: object, maximum_items: int = 16) -> bool:
    if type(value) is not list:
        return False
    items = cast(list[object], value)
    return len(items) <= maximum_items and all(
        _text_or_none(item, 512) and item is not None for item in items
    )


def _self(value: dict[str, object]) -> None:
    if (
        set(value)
        != {
            "schema_version",
            "identity_kind",
            "creator_role_awareness",
            "name",
            "self_description",
            "interests",
            "values",
            "preferences",
            "goals",
            "self_narrative",
            "tensions",
        }
        or value["schema_version"] != "armi.self.v1"
        or value["identity_kind"] != "electronic_person"
        or value["creator_role_awareness"] != "unique_primary_creator"
    ):
        raise ValueError
    if (
        not _text_or_none(value["name"], 128)
        or not _text_or_none(value["self_description"], 2048)
        or not _text_or_none(value["self_narrative"], 2048)
    ):
        raise ValueError
    if not all(
        _texts(value[key])
        for key in ("interests", "values", "preferences", "goals", "tensions")
    ):
        raise ValueError


def _mind(value: dict[str, object]) -> None:
    if (
        set(value)
        != {
            "schema_version",
            "understanding",
            "attention",
            "emotions",
            "thoughts",
            "wishes",
            "motivations",
            "mood",
        }
        or value["schema_version"] != "armi.mind.v1"
    ):
        raise ValueError
    if not all(
        _texts(value[key])
        for key in (
            "understanding",
            "attention",
            "emotions",
            "thoughts",
            "wishes",
            "motivations",
        )
    ) or not _text_or_none(value["mood"], 128):
        raise ValueError


def _life_mode(value: dict[str, object]) -> None:
    if (
        set(value) != {"schema_version", "mode", "active_activities"}
        or value["schema_version"] != "armi.life-mode.v1"
        or value["mode"] != "awake"
    ):
        raise ValueError
    active = value["active_activities"]
    if type(active) is not list:
        raise ValueError
    active_items = cast(list[object], active)
    if len(active_items) > 1 or any(type(item) is not str for item in active_items):
        raise ValueError


__all__ = ("validate_candidate", "validate_state")
