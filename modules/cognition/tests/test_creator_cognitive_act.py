# ruff: noqa: RUF001

from __future__ import annotations

import json

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


def test_text_contract_is_strict_and_single() -> None:
    candidate = parse_creator_cognitive_act(
        {
            "kind": "reply",
            "content": "好，我知道了。",
            "record_kind": None,
            "query": None,
            "experience": {
                "first_person_gist": "Creator 告诉了我一件事",
                "uncertainty": None,
                "remember": False,
                "memory_summary": None,
            },
            "appraisal": None,
            "changes": [],
        },
        allowed_context_refs=frozenset(),
    )
    assert isinstance(candidate, CreatorCognitiveActCandidate)
    assert candidate.schema_version == CREATOR_COGNITIVE_ACT_VERSION
    assert creator_cognitive_act_schema()["additionalProperties"] is False


def test_extra_fields_reject_the_whole_act() -> None:
    with pytest.raises(ValidationError):
        CreatorCognitiveActCandidate.model_validate(
            {
                "kind": "no_action",
                "content": None,
                "record_kind": None,
                "query": None,
                "experience": None,
                "appraisal": None,
                "changes": [],
                "mood_score": 0.5,
            },
            strict=True,
        )


def test_voice_wire_expands_to_the_same_semantics() -> None:
    candidate = parse_creator_voice_act(
        {
            "k": "reply",
            "text": "我听见了。",
            "record": None,
            "query": None,
            "exp": {"g": "Creator 正在和我说话", "u": None, "m": None},
            "app": None,
            "ops": [],
        },
        allowed_context_refs=frozenset(),
    )
    assert candidate.kind == "reply"
    assert candidate.content == "我听见了。"
    assert candidate.experience is not None
    assert candidate.experience.remember is False


def test_voice_memory_is_explicit_by_presence() -> None:
    candidate = parse_creator_voice_act(
        {
            "k": "no_change",
            "text": None,
            "record": None,
            "query": None,
            "exp": {"g": "Creator 明确让我记住", "u": None, "m": "需要记住的事"},
            "app": None,
            "ops": [],
        },
        allowed_context_refs=frozenset(),
    )
    assert candidate.experience is not None
    assert candidate.experience.remember is True


def test_voice_appraisal_and_operations_use_short_wire_fields_without_losing_meaning() -> (
    None
):
    candidate = parse_creator_voice_act(
        {
            "k": "reply",
            "text": "我明白。",
            "record": None,
            "query": None,
            "exp": {"g": "Creator 肯定了我的选择", "u": None, "m": None},
            "app": {
                "t": "new",
                "r": None,
                "p": "realized",
                "g": "受到肯定",
                "d": None,
                "a": {
                    "c": [{"t": "relationship", "s": "direct", "d": "progress"}],
                    "e": "somewhat_unexpected",
                    "o": "settled",
                    "q": "pleasant",
                    "i": "important",
                    "d": None,
                    "a": None,
                    "p": None,
                    "s": None,
                },
                "b": ["ctx:1"],
            },
            "ops": [
                {
                    "o": "relationship.fact",
                    "r": None,
                    "l": None,
                    "f": None,
                    "p": None,
                    "t": "Creator 表达了肯定",
                    "i": None,
                    "m": {},
                }
            ],
        },
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert candidate.appraisal is not None
    assert candidate.appraisal.appraisal.expectedness == "somewhat_unexpected"
    assert candidate.changes[0].op == "relationship.fact"
    schema = json.dumps(creator_voice_act_schema(), ensure_ascii=False)
    assert '"expectedness"' not in schema
    assert '"target_ref"' not in schema
