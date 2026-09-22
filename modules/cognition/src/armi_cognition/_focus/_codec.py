"""Canonical owner-draft codec for Focus."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from .api import (
    CONCERN_CHANGES,
    CandidateFocusDraft,
    FocusViolation,
)

_KEYS = {
    "schema_kind",
    "proposal_ref",
    "atomic_group_ref",
    "basis_ordinals",
    "fact_class",
    "expected_version",
    "next_state",
    "concern_changes",
}


def encode(value: CandidateFocusDraft) -> bytes:
    next_state = cast(object, json.loads(value.canonical_next_state))
    document: dict[str, object] = {
        "schema_kind": "armi.focus-candidate",
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "expected_version": value.expected_version,
        "next_state": next_state,
        "concern_changes": [
            item.model_dump(mode="json") for item in value.concern_changes
        ],
    }
    return rfc8785.dumps(cast(Any, document))


def decode(payload: bytes) -> CandidateFocusDraft:
    try:
        raw_value = cast(object, json.loads(payload))
        if type(raw_value) is not dict:
            raise ValueError
        raw = cast(dict[str, object], raw_value)
        if (
            set(raw) != _KEYS
            or raw["schema_kind"] != "armi.focus-candidate"
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
            or type(raw["expected_version"]) is not int
        ):
            raise ValueError
        return CandidateFocusDraft(
            raw["proposal_ref"],
            raw["atomic_group_ref"],
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(raw["fact_class"]),
            raw["expected_version"],
            rfc8785.dumps(cast(Any, raw["next_state"])),
            CONCERN_CHANGES.validate_json(
                json.dumps(raw["concern_changes"]), strict=True
            ),
        )
    except UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise FocusViolation("FOCUS-CODEC") from None


def bind(value: CandidateFocusDraft) -> CandidateOwnerDraft:
    return CandidateOwnerDraft(
        value.proposal_ref,
        value.atomic_group_ref,
        value.basis_ordinals,
        value.fact_class,
        "focus",
        encode(value),
        value,
    )


__all__ = ("bind", "decode", "encode")
