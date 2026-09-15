"""Behavioral equivalence of Creator text and voice contracts."""

from __future__ import annotations

import json

import jsonschema
import pytest
from armi_cognition._creator_cognitive_act_contract import (
    CREATOR_COGNITIVE_ACT_VERSION,
    CreatorCognitiveActCandidate,
    creator_cognitive_act_schema,
    creator_voice_act_schema,
    parse_creator_cognitive_act,
    parse_creator_voice_act,
)
from pydantic import ValidationError


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
        {"kind": "web_research", "query": "public facts"},
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
