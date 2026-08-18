"""Canonical owner-draft codec for mood commands."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from ._domain import component_to_wire, parse_component, parse_vad, vad_to_wire
from .api import (
    AffectiveEvent,
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
    command: dict[str, object]
    if value.kind is MoodCandidateKind.EVENT:
        if value.event is None:
            raise MoodViolation("MOOD-CODEC")
        command = {
            "importance": value.event.importance,
            "components": [component_to_wire(item) for item in value.event.components],
        }
    else:
        if value.target_home_base is None:
            raise MoodViolation("MOOD-CODEC")
        command = {"target_home_base": vad_to_wire(value.target_home_base)}
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.mood-candidate.v2",
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
            or raw["schema_version"] != "armi.mood-candidate.v2"
            or rfc8785.dumps(cast(Any, raw)) != payload
            or type(ordinals) is not list
            or any(type(item) is not int for item in cast(list[object], ordinals))
            or type(raw["proposal_ref"]) is not str
            or type(raw["atomic_group_ref"]) is not str
            or type(raw["fact_class"]) is not str
            or type(raw["expected_version"]) is not int
            or type(raw["kind"]) is not str
            or type(command) is not dict
        ):
            raise ValueError
        kind = MoodCandidateKind(cast(str, raw["kind"]))
        event = None
        target = None
        command_map = cast(dict[str, object], command)
        if kind is MoodCandidateKind.EVENT:
            components = command_map.get("components")
            if (
                set(command_map) != {"importance", "components"}
                or type(command_map["importance"]) is not int
                or type(components) is not list
            ):
                raise ValueError
            event = AffectiveEvent(
                cast(int, command_map["importance"]),
                tuple(parse_component(item) for item in cast(list[object], components)),
            )
        else:
            if set(command_map) != {"target_home_base"}:
                raise ValueError
            target = parse_vad(command_map["target_home_base"])
        return CandidateMoodDraft(
            cast(str, raw["proposal_ref"]),
            cast(str, raw["atomic_group_ref"]),
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(cast(str, raw["fact_class"])),
            cast(int, raw["expected_version"]),
            kind,
            event,
            target,
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
