"""Canonical owner-draft codec for mood."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from .api import CandidateMoodDraft, MoodViolation

_KEYS = {
    "schema_version",
    "proposal_ref",
    "atomic_group_ref",
    "basis_ordinals",
    "fact_class",
    "expected_version",
    "next_state",
}


def encode(value: CandidateMoodDraft) -> bytes:
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.mood-candidate.v1",
                "proposal_ref": value.proposal_ref,
                "atomic_group_ref": value.atomic_group_ref,
                "basis_ordinals": list(value.basis_ordinals),
                "fact_class": value.fact_class.value,
                "expected_version": value.expected_version,
                "next_state": json.loads(value.canonical_next_state),
            },
        )
    )


def decode(payload: bytes) -> CandidateMoodDraft:
    try:
        raw_value = cast(object, json.loads(payload))
        if type(raw_value) is not dict:
            raise ValueError
        raw = cast(dict[str, object], raw_value)
        ordinals = raw["basis_ordinals"]
        if (
            set(raw) != _KEYS
            or raw["schema_version"] != "armi.mood-candidate.v1"
            or rfc8785.dumps(cast(Any, raw)) != payload
            or type(ordinals) is not list
            or any(type(item) is not int for item in cast(list[object], ordinals))
            or type(raw["proposal_ref"]) is not str
            or type(raw["atomic_group_ref"]) is not str
            or type(raw["fact_class"]) is not str
            or type(raw["expected_version"]) is not int
        ):
            raise ValueError
        return CandidateMoodDraft(
            raw["proposal_ref"],
            raw["atomic_group_ref"],
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(raw["fact_class"]),
            raw["expected_version"],
            rfc8785.dumps(cast(Any, raw["next_state"])),
        )
    except UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise MoodViolation("MOOD-CODEC") from None


def bind(value: CandidateMoodDraft) -> CandidateOwnerDraft:
    return CandidateOwnerDraft(
        value.proposal_ref,
        value.atomic_group_ref,
        value.basis_ordinals,
        value.fact_class,
        "mood",
        encode(value),
    )


__all__ = ("bind", "decode", "encode")
