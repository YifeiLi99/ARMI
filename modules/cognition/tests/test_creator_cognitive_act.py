"""Behavioral equivalence of Creator text and voice contracts."""

from __future__ import annotations

import json
from typing import cast

import jsonschema
import pytest
from armi_cognition._creator_changes import translate_creator_changes
from armi_cognition._creator_cognitive_act_contract import (
    CREATOR_COGNITIVE_ACT_VERSION,
    CreatorCognitiveActCandidate,
    creator_cognitive_act_schema,
    creator_voice_act_schema,
    parse_creator_cognitive_act,
    parse_creator_voice_act,
)
from pydantic import BaseModel, ValidationError


@pytest.mark.parametrize(
    "decision",
    [
        {"kind": "reply", "content": "Hello"},
        {"kind": "decline", "content": "I decline"},
        {"kind": "need_information", "content": "Which document?"},
        {"kind": "no_change", "content": "The current value is correct"},
        {"kind": "defer", "content": "I will consider this later"},
        {"kind": "no_action"},
        {"kind": "exact_life_query", "record_kind": "memory"},
        {"kind": "exact_life_query", "record_kind": "memory", "query": "last week"},
        {"kind": "web_research", "query": "public facts"},
        {
            "kind": "codex_delegation",
            "objective": "Compare official sources",
            "web_search": True,
        },
        {"kind": "visual_observation", "source_kind": "camera"},
        {"kind": "visual_observation", "source_kind": "screen"},
    ],
)
def test_all_actions_have_the_same_text_and_voice_semantics(decision):
    text_value = {"decision": decision}
    voice_value = {"d": decision}
    jsonschema.validate(text_value, creator_cognitive_act_schema())
    jsonschema.validate(voice_value, creator_voice_act_schema())
    text = parse_creator_cognitive_act(text_value, allowed_context_refs=frozenset())
    voice = parse_creator_voice_act(voice_value, allowed_context_refs=frozenset())
    assert isinstance(text, CreatorCognitiveActCandidate)
    assert text.schema_version == CREATOR_COGNITIVE_ACT_VERSION
    assert text.model_dump() == voice.model_dump()


def test_memory_is_explicit_by_summary_presence():
    for summary in (None, "Remember this fact"):
        experience = {"first_person_gist": "Creator told me", "memory_summary": summary}
        text = parse_creator_cognitive_act(
            {"decision": {"kind": "no_change"}, "experience": experience},
            allowed_context_refs=frozenset(),
        )
        voice = parse_creator_voice_act(
            {"d": {"kind": "no_change"}, "exp": experience},
            allowed_context_refs=frozenset(),
        )
        assert text.experience == voice.experience
        assert text.experience is not None
        assert text.experience.remember is (summary is not None)


@pytest.mark.parametrize(
    "value",
    [
        {"decision": {"kind": "reply", "content": "ok", "query": "unrelated"}},
        {
            "decision": {
                "kind": "exact_life_query",
                "record_kind": "memory",
                "content": "ok",
            }
        },
        {"decision": {"kind": "no_action"}, "mood_score": 0.5},
        {
            "decision": {"kind": "no_action"},
            "experience": {
                "first_person_gist": "fact",
                "remember": False,
                "memory_summary": "contradiction",
            },
        },
    ],
)
def test_invalid_fields_reject_the_whole_act(value):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, creator_cognitive_act_schema())
    with pytest.raises(ValidationError):
        parse_creator_cognitive_act(value, allowed_context_refs=frozenset())


def test_voice_expression_limit_is_shared_by_reply_and_terminal():
    for kind in ("reply", "decline", "need_information"):
        value = {"d": {"kind": kind, "content": "x" * 61}}
        with pytest.raises(ValidationError):
            parse_creator_voice_act(value, allowed_context_refs=frozenset())


def test_voice_appraisal_and_operations_share_business_types():
    appraisal = {
        "trajectory": {"transition": "new"},
        "event_phase": "realized",
        "gist": "Recognition",
        "appraisal": {
            "concerns": [
                {
                    "target": "relationship",
                    "significance": "direct",
                    "direction": "progress",
                }
            ],
            "expectedness": "somewhat_unexpected",
            "outcome_certainty": "settled",
            "intrinsic_quality": "pleasant",
            "self_involvement": "important",
        },
        "basis_refs": ["ctx:1"],
    }
    changes = [{"op": "relationship.fact", "text": "Creator acknowledged my choice"}]
    experience = {"first_person_gist": "Creator acknowledged my choice"}
    candidate = parse_creator_voice_act(
        {
            "d": {"kind": "reply", "content": "Understood"},
            "exp": experience,
            "app": appraisal,
            "ops": changes,
        },
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    text = parse_creator_cognitive_act(
        {
            "decision": {"kind": "reply", "content": "Understood"},
            "experience": experience,
            "appraisal": appraisal,
            "changes": changes,
        },
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert candidate.model_dump() == text.model_dump()
    assert candidate.appraisal is not None
    assert candidate.appraisal.appraisal.expectedness == "somewhat_unexpected"
    assert candidate.changes[0].op == "relationship.fact"
    schema = json.dumps(creator_voice_act_schema())
    assert "VoiceSemanticAppraisal" not in schema
    assert "AppraisalSemanticSignal" in schema


@pytest.mark.parametrize(
    ("change", "owner", "expected"),
    [
        (
            {
                "op": "material.create",
                "material_kind": "diary",
                "content": {
                    "title": "Today",
                    "body": "An experience",
                    "metadata": {"topic": "life"},
                },
            },
            "material_change",
            {
                "action": "create",
                "material_kind": "diary",
                "metadata": {"topic": "life"},
            },
        ),
        (
            {
                "op": "material.update",
                "target_ref": "ctx:1",
                "content": {"title": "Revised", "body": "New meaning"},
            },
            "material_change",
            {"action": "update", "material_ref": "ctx:1", "title": "Revised"},
        ),
        (
            {
                "op": "material.visibility",
                "target_ref": "ctx:1",
                "visibility": "set_private",
            },
            "material_change",
            {"action": "set_private", "material_ref": "ctx:1"},
        ),
        (
            {"op": "material.delete", "target_ref": "ctx:1"},
            "material_change",
            {"action": "delete", "material_ref": "ctx:1"},
        ),
        (
            {"op": "relationship.interpret", "text": "Trust"},
            "relationship_change",
            {"interpretation": "Trust"},
        ),
        (
            {"op": "relationship.fact", "text": "They asked"},
            "relationship_change",
            {"fact": {"kind": "party_expression", "summary": "They asked"}},
        ),
        (
            {
                "op": "relationship.boundary",
                "party": "creator",
                "boundary": {"kind": "exit", "action": "end_contact"},
                "text": "Stop",
            },
            "relationship_change",
            {
                "boundary": {
                    "party": "creator",
                    "kind": "exit",
                    "action": "end_contact",
                    "summary": "Stop",
                }
            },
        ),
        (
            {
                "op": "commitment.establish",
                "party": "armi",
                "scope": "Contact",
                "content": "Ask first",
                "event_summary": "Agreed",
                "conflicts_with_ref": "ctx:2",
            },
            "commitment_change",
            {"action": "establish", "scope": "Contact", "conflicts_with_ref": "ctx:2"},
        ),
        (
            {
                "op": "commitment.modify",
                "target_ref": "ctx:1",
                "update": {"kind": "content", "content": "Weekdays"},
                "event_summary": "Revised",
            },
            "commitment_change",
            {"action": "modify", "scope": None, "content": "Weekdays"},
        ),
        (
            {
                "op": "commitment.modify",
                "target_ref": "ctx:1",
                "update": {"kind": "scope", "scope": "Work", "content": "Weekdays"},
                "event_summary": "Revised",
            },
            "commitment_change",
            {"action": "modify", "scope": "Work", "content": "Weekdays"},
        ),
        *[
            (
                {"op": f"commitment.{action}", "target_ref": "ctx:1", "text": "Event"},
                "commitment_change",
                {"action": action, "commitment_ref": "ctx:1", "event_summary": "Event"},
            )
            for action in ("fulfill", "withdraw", "forget", "violate")
        ],
        (
            {
                "op": "commitment.conflict",
                "target_ref": "ctx:1",
                "related_ref": "ctx:2",
                "text": "Conflict",
            },
            "commitment_change",
            {
                "action": "note_conflict",
                "commitment_ref": "ctx:1",
                "conflicts_with_ref": "ctx:2",
            },
        ),
    ],
)
def test_every_creator_change_has_shared_schema_and_owner_mapping(
    change, owner, expected
):
    text_value = {"decision": {"kind": "no_change"}, "changes": [change]}
    voice_value = {"d": {"kind": "no_change"}, "ops": [change]}
    jsonschema.validate(text_value, creator_cognitive_act_schema())
    jsonschema.validate(voice_value, creator_voice_act_schema())
    refs = frozenset({"ctx:1", "ctx:2"})
    text = parse_creator_cognitive_act(text_value, allowed_context_refs=refs)
    voice = parse_creator_voice_act(voice_value, allowed_context_refs=refs)
    assert text.changes == voice.changes
    translated = translate_creator_changes(text.changes)
    value = cast(
        BaseModel,
        translated["relationship_change" if owner == "commitment_change" else owner],
    ).model_dump()
    if owner == "commitment_change":
        value = value["commitment_change"]
    assert {key: value[key] for key in expected} == expected


@pytest.mark.parametrize(
    "change",
    [
        {"op": "material.delete", "target_ref": "ctx:1", "text": "Unused"},
        {"op": "material.create", "content": {"title": "Missing kind", "body": "Body"}},
        {
            "op": "relationship.boundary",
            "party": "armi",
            "boundary": {"kind": "contact", "action": "end_contact"},
            "text": "Invalid",
        },
        {
            "op": "commitment.modify",
            "target_ref": "ctx:1",
            "update": {"kind": "content"},
            "event_summary": "Empty",
        },
        {
            "op": "commitment.fulfill",
            "target_ref": "ctx:1",
            "text": "Done",
            "scope": "Unused",
        },
        {
            "op": "commitment.conflict",
            "target_ref": "ctx:1",
            "text": "Missing reference",
        },
    ],
)
def test_change_dependencies_are_visible_in_schema(change):
    value = {"decision": {"kind": "no_action"}, "changes": [change]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, creator_cognitive_act_schema())
    with pytest.raises(ValidationError):
        parse_creator_cognitive_act(value, allowed_context_refs=frozenset({"ctx:1"}))
