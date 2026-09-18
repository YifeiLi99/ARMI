"""The schema actually sent to a provider and local contracts share static rules."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from armi_kernel.application import ModelViolation
from armi_mind.api import DialogueMindChange
from armi_mood.api import (
    AppraisalSemanticSignal,
    MoodSemanticAppraisalCommand,
    MoodViolation,
    semantic_appraisal_from_command,
)
from armi_runtime.adapters.model.volcengine_ark import _provider_output_schema
from armi_runtime.composition.model_verification import (
    candidate_schema,
    parse_candidate,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError


def _provider(schema):
    return Draft202012Validator(
        _provider_output_schema(schema, available_refs=("ctx:1",))
    )


def _signal():
    return {
        "engagement": "satisfying",
        "concerns": [
            {"target": "self_goal", "significance": "direct", "direction": "unchanged"}
        ],
        "expectedness": "somewhat_unexpected",
        "outcome_certainty": "open",
        "intrinsic_quality": "pleasant",
        "self_involvement": "important",
        "demand": None,
        "causality": None,
        "coping": None,
        "standards": None,
    }


@pytest.mark.parametrize(
    "text,accepted",
    [
        (" unexplained light change", False),
        ("说明 \n", False),
        ("多行\n摘要", True),
        ("", False),
        (" \n\t", False),
        ("\x1c\x1d\x1e\x1f", False),
        ("bad\x00text", False),
        ("x" * 65, False),
    ],
)
def test_mood_gist_schema_parser_and_owner_agree_without_trimming(text, accepted):
    value = dict(
        schema_version="armi.mood-appraisal.v3",
        transition="new",
        previous_episode_id=None,
        event_phase="ongoing",
        gist=text,
        change_from_previous=None,
        appraisal=_signal(),
    )
    assert (
        _provider(MoodSemanticAppraisalCommand.model_json_schema()).is_valid(
            {"candidate": value}
        )
        is accepted
    )
    if accepted:
        typed = MoodSemanticAppraisalCommand.model_validate_json(json.dumps(value))
        assert semantic_appraisal_from_command(typed).gist == text
    else:
        with pytest.raises(ValidationError):
            MoodSemanticAppraisalCommand.model_validate_json(json.dumps(value))


def test_mood_conflicting_assessments_remain_an_owner_semantic_rejection():
    value = _signal()
    value["concerns"].append(
        {"target": "self_goal", "significance": "core", "direction": "fulfilled"}
    )
    assert _provider(AppraisalSemanticSignal.model_json_schema()).is_valid(
        {"candidate": value}
    )
    typed = AppraisalSemanticSignal.model_validate_json(json.dumps(value))
    command = MoodSemanticAppraisalCommand(
        schema_version="armi.mood-appraisal.v3",
        transition="new",
        previous_episode_id=None,
        event_phase="ongoing",
        gist="conflicting assessments",
        change_from_previous=None,
        appraisal=typed,
    )
    with pytest.raises(MoodViolation):
        semantic_appraisal_from_command(command)
    value["concerns"][-1]["target"] = "relationship"
    assert _provider(AppraisalSemanticSignal.model_json_schema()).is_valid(
        {"candidate": value}
    )
    AppraisalSemanticSignal.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "values,accepted",
    [(None, False), (["x", "x"], False), ([" "], False), ([], True), ([" x "], True)],
)
def test_mind_nonempty_change_and_unique_text_are_visible_to_provider(values, accepted):
    value: dict[str, Any] = {key: None for key in DialogueMindChange.model_fields}
    if values is not None:
        value["thoughts"] = {"values": values}
    assert (
        _provider(DialogueMindChange.model_json_schema()).is_valid({"candidate": value})
        is accepted
    )
    if accepted:
        DialogueMindChange.model_validate_json(json.dumps(value))
    else:
        with pytest.raises(ValidationError):
            DialogueMindChange.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "version,value,path",
    [
        (
            "armi.creator-cognitive-act-candidate.v7",
            {"decision": {"kind": "reply", "content": "ok"}},
            ("decision", "content"),
        ),
        (
            "armi.creator-voice-act-candidate.v7",
            {"d": {"kind": "reply", "content": "ok"}},
            ("d", "content"),
        ),
        (
            "armi.other-human-dialogue-candidate.v9",
            {"decision": {"kind": "reply", "content": "ok"}},
            ("decision", "content"),
        ),
        (
            "armi.autonomous-activity-candidate.v10",
            {
                "kind": "no_activity",
                "next_consideration_seconds": 60,
                "expression": "ok",
            },
            ("expression",),
        ),
        (
            "armi.maintenance-work-candidate.v3",
            {"kind": "memory_unchanged", "summary": "ok"},
            ("summary",),
        ),
    ],
)
@pytest.mark.parametrize(
    "text,accepted",
    [(" hello \n", True), (" \n\t", False), ("\x1c", False), ("a\x00b", False)],
)
def test_expression_and_summary_rules_match_on_all_channels(
    version, value, path, text, accepted
):
    parsed = parse_candidate(
        json.dumps(value).encode(),
        expected_version=version,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    document = deepcopy(parsed.model_dump(mode="json", by_alias=True))
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = text
    assert (
        _provider(candidate_schema(version)).is_valid({"candidate": document})
        is accepted
    )
    if accepted:
        parse_candidate(
            json.dumps(document).encode(),
            expected_version=version,
            allowed_context_refs=frozenset({"ctx:1"}),
        )
    else:
        with pytest.raises((ValidationError, ModelViolation, ValueError)):
            parse_candidate(
                json.dumps(document).encode(),
                expected_version=version,
                allowed_context_refs=frozenset({"ctx:1"}),
            )


@pytest.mark.parametrize(
    "seconds,accepted",
    [(60, True), (60.0, True), (60.5, False), ("60", False), (True, False)],
)
def test_json_schema_integer_semantics_match_the_single_parser(seconds, accepted):
    version = "armi.autonomous-activity-candidate.v10"
    value = {
        "kind": "no_activity",
        "next_consideration_seconds": seconds,
        "mind_appraisals": [],
        "concern_changes": [],
        "mind_change": None,
        "appraisal": None,
        "expression": None,
    }
    assert (
        _provider(candidate_schema(version)).is_valid({"candidate": value}) is accepted
    )
    if accepted:
        parsed = parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            allowed_context_refs=frozenset(),
        )
        decoded_seconds = parsed.model_dump()["next_consideration_seconds"]
        assert type(decoded_seconds) is int
        assert decoded_seconds == 60
    else:
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(value).encode(),
                expected_version=version,
                allowed_context_refs=frozenset(),
            )
