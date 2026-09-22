"""Shallow dialogue wire projection; domain candidates retain their owner contracts."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast

from armi_kernel.application import CandidateViolation

from ._autonomous_activity_contract import AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION
from ._creator_cognitive_act_contract import CREATOR_COGNITIVE_ACT_VERSION
from ._other_human_contract import OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION


def _message_schema(text: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in text:
        text = root["$defs"][text["$ref"].removeprefix("#/$defs/")]
    if "anyOf" in text:
        return {"anyOf": [_message_schema(item, root) for item in text["anyOf"]]}
    if text.get("type") != "string":
        return text
    # Model selects actual messages. Blank paragraphs cannot introduce hidden
    # extra messages in the owner's existing text representation (DESIGN.md).
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 3,
        "items": {**text, "not": {"pattern": r"\r?\n[ \t]*\r?\n|^[\r\n]|[\r\n]$"}},
    }


def _join_messages(value: Any) -> str:
    if not isinstance(value, list):
        raise CandidateViolation("CANDIDATE-CONTRACT")
    messages = cast(list[Any], value)
    if not 1 <= len(messages) <= 3 or any(
        not isinstance(part, str)
        or not part.strip()
        or "\x00" in part
        or re.search(r"\r?\n[ \t]*\r?\n|^[\r\n]|[\r\n]$", part)
        for part in messages
    ):
        raise CandidateViolation("CANDIDATE-CONTRACT")
    return "\n\n".join(messages)


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
_CREATOR_STATE = frozenset({"changes", "mind_appraisals", "concern_changes"})


def dialogue_output_instructions(instructions: str) -> str:
    return instructions


def dialogue_output_kind(properties: set[str]) -> str | None:
    if properties == {"decision", "social"}:
        return "other"
    if properties == {"decision", "experience", *_CREATOR_STATE}:
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

        def project_expression(value: Any) -> None:
            if isinstance(value, dict):
                node = cast(dict[str, Any], value)
                properties = node.get("properties", {})
                if "kind" in properties and "expression" in properties:
                    properties["expression"] = _message_schema(
                        properties["expression"], root
                    )
                for child in node.values():
                    project_expression(child)
            elif isinstance(value, list):
                for child in cast(list[Any], value):
                    project_expression(child)

        project_expression(root)
        return root
    # Replace only the decision's outward text; memory/relationship content stays
    # plain text. Both providers see the same message-array contract.
    for branch in objects(props["decision"]):
        if "content" in branch["properties"]:
            branch["properties"]["content"] = _message_schema(
                branch["properties"]["content"], root
            )
    result = new_object()
    lift(result, props["decision"], _DECISION, optional=False)
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
    if expected_version == "armi.autonomy-check-candidate":
        # The check has its own single-field wire contract, no candidate wrapper.
        return value
    other = expected_version == OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
    if expected_version not in {
        CREATOR_COGNITIVE_ACT_VERSION,
        OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    }:
        if set(value) != {"candidate"} or not isinstance(value["candidate"], dict):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        candidate = cast(dict[str, Any], value["candidate"])
        if (
            expected_version == AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION
            and candidate.get("expression") is not None
        ):
            candidate = {
                **candidate,
                "expression": _join_messages(candidate["expression"]),
            }
        return candidate
    allowed = set(_DECISION) | set(_EXPERIENCE)
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
    if "content" in result["decision"] and result["decision"]["content"] is not None:
        result["decision"]["content"] = _join_messages(result["decision"]["content"])
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
    return result


def flatten_dialogue_output(candidate: dict[str, Any]) -> dict[str, Any]:
    """Encode examples/fixtures using the same field mapping as real decoding."""
    value = {
        new: candidate["decision"][old]
        for new, old in _DECISION.items()
        if old in candidate["decision"]
    }
    if value.get("content") is not None:
        value["content"] = [value["content"]]
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
    return value
