"""Canonical owner-draft codec for mood commands."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from ._domain import appraisal_to_wire, parse_appraisal
from .api import (
    CandidateMoodDraft,
    MoodCandidateKind,
    MoodViolation,
)

_COMMON_KEYS = {
    "schema_version",
    "proposal_ref",
    "atomic_group_ref",
    "basis_ordinals",
    "fact_class",
    "expected_version",
    "kind",
}


def encode(value: CandidateMoodDraft) -> bytes:
    command: dict[str, object] | None
    if value.kind is MoodCandidateKind.APPRAISAL:
        if value.appraisal is None:
            raise MoodViolation("MOOD-CODEC")
        command = appraisal_to_wire(value.appraisal)
    else:
        if value.appraisal is not None:
            raise MoodViolation("MOOD-CODEC")
        command = None
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.mood-candidate.v3",
                "proposal_ref": value.proposal_ref,
                "atomic_group_ref": value.atomic_group_ref,
                "basis_ordinals": list(value.basis_ordinals),
                "fact_class": value.fact_class.value,
                "expected_version": value.expected_version,
                "kind": value.kind.value,
                "command": command,
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
        command = raw["command"]
        if (
            set(raw) != _COMMON_KEYS | {"command"}
            or raw["schema_version"] != "armi.mood-candidate.v3"
            or rfc8785.dumps(cast(Any, raw)) != payload
            or type(ordinals) is not list
            or any(type(item) is not int for item in cast(list[object], ordinals))
            or type(raw["proposal_ref"]) is not str
            or type(raw["atomic_group_ref"]) is not str
            or type(raw["fact_class"]) is not str
            or type(raw["expected_version"]) is not int
            or type(raw["kind"]) is not str
            or (command is not None and type(command) is not dict)
        ):
            raise ValueError
        kind = MoodCandidateKind(cast(str, raw["kind"]))
        appraisal = None
        if kind is MoodCandidateKind.APPRAISAL:
            if type(command) is not dict:
                raise ValueError
            appraisal = parse_appraisal(command)
        else:
            if command is not None:
                raise ValueError
        return CandidateMoodDraft(
            cast(str, raw["proposal_ref"]),
            cast(str, raw["atomic_group_ref"]),
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(cast(str, raw["fact_class"])),
            cast(int, raw["expected_version"]),
            kind,
            appraisal,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        MoodViolation,
        TypeError,
        ValueError,
    ):
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
