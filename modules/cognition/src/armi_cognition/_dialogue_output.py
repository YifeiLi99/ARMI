"""Shallow dialogue wire projection; domain candidates retain their owner contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from armi_kernel.application import CandidateViolation

from ._creator_cognitive_act_contract import CREATOR_COGNITIVE_ACT_VERSION
from ._other_human_contract import OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION

_DECISION = {
    "action": "kind",
    "content": "content",
    "query": "query",
    "record_kind": "record_kind",
    "objective": "objective",
    "web_search": "web_search",
    "source_kind": "source_kind",
}
_EXPERIENCE = {
    "experience": "first_person_gist",
    "experience_uncertainty": "uncertainty",
    "memory_summary": "memory_summary",
}
_RELATIONSHIP = {
    "relationship_interpretation": "interpretation",
    "relationship_fact": "fact",
    "relationship_boundary": "boundary",
    "commitment_change": "commitment_change",
}
_SEMANTICS = frozenset(
    {
        "engagement",
        "concerns",
        "expectedness",
        "outcome_certainty",
        "intrinsic_quality",
        "self_involvement",
        "demand",
        "causality",
        "coping",
        "standards",
    }
)
_TRAJECTORY = frozenset({"transition", "episode_ref", "change_from_previous"})
_EVENT = frozenset({"gist", "basis_refs", "event_phase"})
_CREATOR_STATE = frozenset({"changes", "mind_appraisals", "concern_changes"})


def dialogue_output_kind(properties: set[str]) -> str | None:
    if properties == {"decision", "appraisal", "social"}:
        return "other"
    if properties == {"decision", "appraisal", "experience", *_CREATOR_STATE}:
        return "creator"
    return None


def dialogue_output_schema(envelope: dict[str, Any]) -> dict[str, Any]:
    """Project the already-bound generation schema without inventing constraints."""
    root = deepcopy(envelope)

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in node:
            node = root["$defs"][node["$ref"].removeprefix("#/$defs/")]
        return node

    def objects(node: dict[str, Any]) -> list[dict[str, Any]]:
        node = resolve(node)
        if "anyOf" in node:
            return [leaf for item in node["anyOf"] for leaf in objects(item)]
        return [node] if node.get("type") == "object" else []

    def lift(
        target: dict[str, Any],
        node: dict[str, Any],
        names: dict[str, str],
        *,
        optional: bool,
    ) -> None:
        branches = objects(node)
        keys = {
            new
            for new, old in names.items()
            if any(old in b["properties"] for b in branches)
        }
        choices: list[dict[str, Any]] = []
        for branch in branches:
            properties = {
                new: branch["properties"][old]
                for new, old in names.items()
                if old in branch["properties"]
            }
            required = [
                new for new, old in names.items() if old in branch.get("required", [])
            ]
            # Constraints cover only this group. The root rejects unknown fields.
            choices.append(
                {
                    "properties": {
                        **dict.fromkeys(sorted(keys - properties.keys()), False),
                        **properties,
                    },
                    "required": required,
                }
            )
        for key in names:
            if key not in keys:
                continue
            alternatives: list[Any] = []
            for choice in choices:
                option = choice["properties"][key]
                if option is not False and option not in alternatives:
                    alternatives.append(option)
            target["properties"][key] = (
                alternatives[0] if len(alternatives) == 1 else {"anyOf": alternatives}
            )
            if len(alternatives) == 1:
                for choice in choices:
                    if choice["properties"][key] is not False:
                        del choice["properties"][key]
        constraint = choices[0] if len(choices) == 1 else {"anyOf": choices}
        if optional:
            constraint = {
                "if": {"anyOf": [{"required": [key]} for key in sorted(keys)]},
                "then": constraint,
            }
        target.setdefault("allOf", []).append(constraint)

    def new_object() -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    candidate = resolve(root["properties"]["candidate"])
    props = candidate.get("properties", {})
    kind = dialogue_output_kind(set(props))
    if kind is None:
        return envelope
    result = new_object()
    lift(result, props["decision"], _DECISION, optional=False)
    event = objects(props["appraisal"])[0]
    flat_event = new_object()
    flat_event["properties"] = {key: event["properties"][key] for key in sorted(_EVENT)}
    flat_event["required"] = sorted(_EVENT)
    lift(
        flat_event,
        event["properties"]["appraisal"],
        {key: key for key in sorted(_SEMANTICS)},
        optional=False,
    )
    lift(
        flat_event,
        event["properties"]["trajectory"],
        {key: key for key in sorted(_TRAJECTORY)},
        optional=False,
    )
    result["properties"]["event_appraisal"] = flat_event
    if kind == "creator":
        lift(result, props["experience"], _EXPERIENCE, optional=True)
        result["properties"].update({key: props[key] for key in sorted(_CREATOR_STATE)})
    else:
        social = objects(props["social"])[0]["properties"]
        lift(result, social["experience"], _EXPERIENCE, optional=True)
        lift(result, social["relationship_change"], _RELATIONSHIP, optional=True)
        result["dependentRequired"] = {key: ["experience"] for key in _RELATIONSHIP}
    result["$defs"] = root.get("$defs", {})
    # Removed wrappers must not leave unreachable branch definitions in the prompt.
    used: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            node = cast(dict[str, Any], value)
            if "$ref" in node:
                name = node["$ref"].removeprefix("#/$defs/")
                if name not in used:
                    used.add(name)
                    visit(result["$defs"][name])
            for key, item in node.items():
                if key != "$defs":
                    visit(item)
        elif isinstance(value, list):
            for item in cast(list[Any], value):
                visit(item)

    visit(result)
    result["$defs"] = {
        name: value for name, value in result["$defs"].items() if name in used
    }
    return result


def expand_dialogue_output(
    value: dict[str, Any], *, expected_version: str
) -> dict[str, Any]:
    """Move known wire fields; downstream domain validation checks all values.

    Never repair JSON, drop unknown fields, infer state or supply missing content.
    Raw provider output remains in the response artifact. See DESIGN.md.
    """
    other = expected_version == OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
    if expected_version not in {
        CREATOR_COGNITIVE_ACT_VERSION,
        OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    }:
        if set(value) != {"candidate"} or not isinstance(value["candidate"], dict):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        return cast(dict[str, Any], value["candidate"])
    allowed = set(_DECISION) | set(_EXPERIENCE) | {"event_appraisal"}
    allowed |= set(_RELATIONSHIP) if other else _CREATOR_STATE
    if other:
        allowed -= {
            "memory_summary",
            "query",
            "record_kind",
            "objective",
            "web_search",
            "source_kind",
        }
    if value.keys() - allowed or "action" not in value:
        raise CandidateViolation("CANDIDATE-CONTRACT")
    result: dict[str, Any] = {
        "decision": {old: value[new] for new, old in _DECISION.items() if new in value}
    }
    experience = {old: value[new] for new, old in _EXPERIENCE.items() if new in value}
    if other:
        relationship = {
            old: value[new] for new, old in _RELATIONSHIP.items() if new in value
        }
        if relationship and (
            not experience
            or not isinstance(relationship.get("interpretation"), str)
            or not relationship["interpretation"].strip()
        ):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        if experience or relationship:
            social: dict[str, Any] = {}
            if experience:
                social["experience"] = experience
            if relationship:
                social["relationship_change"] = relationship
            result["social"] = social
    else:
        if experience:
            result["experience"] = experience
        result.update({key: value[key] for key in _CREATOR_STATE if key in value})
    if "event_appraisal" in value:
        event = value["event_appraisal"]
        if not isinstance(event, dict) or event.keys() - (
            _EVENT | _SEMANTICS | _TRAJECTORY
        ):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        result["appraisal"] = {
            **{key: event[key] for key in _EVENT if key in event},
            "appraisal": {key: event[key] for key in _SEMANTICS if key in event},
            "trajectory": {key: event[key] for key in _TRAJECTORY if key in event},
        }
    return result


def flatten_dialogue_output(candidate: dict[str, Any]) -> dict[str, Any]:
    """Encode examples/fixtures using the same field mapping as real decoding."""
    value = {
        new: candidate["decision"][old]
        for new, old in _DECISION.items()
        if old in candidate["decision"]
    }
    social: dict[str, Any] = candidate.get("social") or {}
    experience: dict[str, Any] = (
        candidate.get("experience") or social.get("experience") or {}
    )
    value.update(
        {new: experience[old] for new, old in _EXPERIENCE.items() if old in experience}
    )
    relationship: dict[str, Any] = social.get("relationship_change") or {}
    value.update(
        {
            new: relationship[old]
            for new, old in _RELATIONSHIP.items()
            if old in relationship
        }
    )
    value.update({key: candidate[key] for key in _CREATOR_STATE if key in candidate})
    if event := candidate.get("appraisal"):
        value["event_appraisal"] = {
            **{key: event[key] for key in _EVENT if key in event},
            **event["appraisal"],
            **event["trajectory"],
        }
    return value
