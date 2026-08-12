"""Canonical owner-draft codec for subject state."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from .api import CandidateSubjectStateDraft, SubjectStateKind, SubjectStateViolation

_KEYS = {
    "schema_version",
    "proposal_ref",
    "atomic_group_ref",
    "basis_ordinals",
    "fact_class",
    "kind",
    "expected_version",
    "next_state",
}


def encode(value: CandidateSubjectStateDraft) -> bytes:
    next_state = cast(object, json.loads(value.canonical_next_state))
    document: dict[str, object] = {
        "schema_version": "armi.subject-state-candidate.v1",
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "kind": value.kind.value,
        "expected_version": value.expected_version,
        "next_state": next_state,
    }
    return rfc8785.dumps(cast(Any, document))


def decode(payload: bytes) -> CandidateSubjectStateDraft:
    try:
        raw_value = cast(object, json.loads(payload))
        if type(raw_value) is not dict:
            raise ValueError
        raw = cast(dict[str, object], raw_value)
        if (
            set(raw) != _KEYS
            or raw["schema_version"] != "armi.subject-state-candidate.v1"
            or rfc8785.dumps(cast(Any, raw)) != payload
        ):
            raise ValueError
        ordinals = raw["basis_ordinals"]
        if type(ordinals) is not list:
            raise ValueError
        ordinal_values = cast(list[object], ordinals)
        if (
            any(type(item) is not int for item in ordinal_values)
            or type(raw["proposal_ref"]) is not str
            or type(raw["atomic_group_ref"]) is not str
            or type(raw["fact_class"]) is not str
            or type(raw["kind"]) is not str
            or type(raw["expected_version"]) is not int
        ):
            raise ValueError
        return CandidateSubjectStateDraft(
            raw["proposal_ref"],
            raw["atomic_group_ref"],
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(raw["fact_class"]),
            SubjectStateKind(raw["kind"]),
            raw["expected_version"],
            rfc8785.dumps(cast(Any, raw["next_state"])),
        )
    except UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise SubjectStateViolation("SUBJECT-STATE-CODEC") from None


def bind(value: CandidateSubjectStateDraft) -> CandidateOwnerDraft:
    return CandidateOwnerDraft(
        value.proposal_ref,
        value.atomic_group_ref,
        value.basis_ordinals,
        value.fact_class,
        value.kind.value,
        encode(value),
    )


__all__ = ("bind", "decode", "encode")
