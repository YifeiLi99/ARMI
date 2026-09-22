"""Shallow provider output reaches the unchanged domain without losing state."""

import json
from typing import Any

import pytest
from armi_cognition._candidate_application import model_response_candidate
from armi_cognition._dialogue_output import flatten_dialogue_output
from armi_cognition._model_contract import parse_candidate
from armi_kernel.application import CandidateViolation, ModelViolation

CREATOR = "armi.creator-cognitive-act-candidate"
OTHER = "armi.other-human-dialogue-candidate"


@pytest.mark.parametrize(
    "version", [CREATOR, OTHER, "armi.autonomous-activity-candidate"]
)
@pytest.mark.parametrize(
    "messages",
    [
        "old string",
        [],
        ["a", "b", "c", "d"],
        [""],
        [" "],
        [42],
        ["a\n\nb"],
        ["a\n"],
        ["\nb"],
        ["bad\x00text"],
    ],
)
def test_message_boundary_contract_rejects_ambiguous_or_invalid_outputs(
    version, messages
):
    wire = (
        {
            "candidate": {
                "kind": "no_activity",
                "expression": messages,
            }
        }
        if "autonomous" in version
        else {"action": "reply", "content": messages}
    )
    with pytest.raises((CandidateViolation, ModelViolation)):
        decode(wire, version)


def decode(value, version) -> Any:
    artifact = json.dumps(
        {
            "schema_kind": "armi.model-response-artifact",
            "output_text": json.dumps(value),
        }
    ).encode()
    candidate = model_response_candidate(artifact, expected_version=version)
    return parse_candidate(
        json.dumps(candidate).encode(),
        expected_version=version,
        allowed_context_refs=frozenset({"ctx:1", "ctx:2"}),
    )


@pytest.mark.parametrize("version", [CREATOR, OTHER])
def test_main_model_cannot_write_event_appraisal(version):
    value = {"action": "reply", "content": ["Got it"], "event_gist": "A loss"}
    with pytest.raises((CandidateViolation, ModelViolation)):
        decode(value, version)


def test_other_experience_relation_boundary_and_commitment_reach_domain():
    value = {
        "action": "reply",
        "content": ["Understood"],
        "experience": "They stated a preference",
        "experience_uncertainty": "The scope needs clarification",
        "relationship_interpretation": "We can talk directly",
        "relationship_fact": {"kind": "party_expression", "summary": "Use this name"},
        "relationship_boundary": {
            "party": "other",
            "kind": "address",
            "action": "restrict",
            "summary": "Use this name",
        },
        "commitment_change": {
            "action": "establish",
            "party": "armi",
            "scope": "This conversation",
            "content": "Use this name",
            "event_summary": "Agreed on the name",
        },
    }
    result = decode(value, OTHER)
    assert result.experience.uncertainty == value["experience_uncertainty"]
    assert result.relationship_change.fact.summary == "Use this name"
    assert result.relationship_change.boundary.kind == "address"
    assert result.relationship_change.commitment_change.content == "Use this name"


def test_creator_memory_and_operations_preserve_values():
    native = {
        "decision": {"kind": "reply", "content": "Remembered"},
        "experience": {
            "first_person_gist": "Creator asked me to remember",
            "uncertainty": "A recollection",
            "memory_summary": "A specific fact",
        },
        "changes": [{"op": "relationship.fact", "text": "A new preference"}],
        "mind_appraisals": [],
        "concern_changes": [],
    }
    result = decode(flatten_dialogue_output(native), CREATOR)
    assert result.experience.memory_summary == "A specific fact"
    assert result.experience.uncertainty == "A recollection"
    assert result.changes[0].text == "A new preference"


def test_creator_concern_is_preserved_without_psychological_write():
    concern = {
        "operation": "create",
        "basis_refs": ["ctx:1"],
        "question": "What happened?",
        "reason": "It matters",
        "resolution_condition": "A direct answer",
        "understanding": "Not yet known",
        "state": "open",
        "review": {"kind": "creator_input", "reason": "Wait for their answer"},
    }
    result = decode(
        {
            "action": "reply",
            "content": ["I will think about it"],
            "concern_changes": [concern],
        },
        CREATOR,
    )
    assert result.concern_changes[0].model_dump(mode="json") == concern


@pytest.mark.parametrize(
    "value",
    [
        {"candidate": {"decision": {"kind": "reply", "content": "Old wrapper"}}},
        {"action": "reply"},
        {"action": "reply", "content": 42},
        {"action": "reply", "content": ["Hi"], "query": "Wrong action field"},
        {"action": "reply", "content": ["Hi"], "_note": "Do not silently drop"},
        {"action": "reply", "content": ["Hi"], "event_appraisal": {"appraisal": {}}},
        {"action": "reply", "content": ["Hi"], "memory_summary": "No experience"},
    ],
)
def test_invalid_shallow_output_is_rejected_without_repair(value):
    with pytest.raises((CandidateViolation, ModelViolation)):
        decode(value, CREATOR)


@pytest.mark.parametrize(
    "extra",
    [
        {"relationship_interpretation": "No experience"},
        {
            "experience": "A conversation",
            "relationship_fact": {
                "kind": "party_expression",
                "summary": "No interpretation",
            },
        },
        {"experience": "A conversation", "memory_summary": "Creator-only capability"},
        {"changes": []},
    ],
)
def test_other_cannot_bypass_relationship_dependencies_or_creator_scope(extra):
    with pytest.raises((CandidateViolation, ModelViolation)):
        decode({"action": "reply", "content": ["Hi"], **extra}, OTHER)
