"""The schema actually sent to a provider and local contracts share static rules."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from armi_kernel.application import ModelViolation
from armi_runtime.adapters.model.structured import _provider_output_schema
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


@pytest.mark.parametrize(
    "version,value,path",
    [
        (
            "armi.creator-cognitive-act-candidate",
            {"decision": {"kind": "reply", "content": "ok"}},
            ("decision", "content"),
        ),
        (
            "armi.creator-voice-act-candidate",
            {"d": {"kind": "reply", "content": "ok"}},
            ("d", "content"),
        ),
        (
            "armi.other-human-dialogue-candidate",
            {"decision": {"kind": "reply", "content": "ok"}},
            ("decision", "content"),
        ),
        (
            "armi.autonomous-activity-candidate",
            {
                "kind": "no_activity",
                "expression": "ok",
            },
            ("expression",),
        ),
        (
            "armi.maintenance-work-candidate",
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
    version = "armi.autonomous-activity-candidate"
    value = {
        "kind": "no_result",
        "reason": "No new evidence",
        "next_step": "Reconsider the activity later",
        "resumption_cue": "review time",
        "review_after_seconds": seconds,
        "concern_changes": [],
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
        decoded_seconds = parsed.model_dump()["review_after_seconds"]
        assert type(decoded_seconds) is int
        assert decoded_seconds == 60
    else:
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(value).encode(),
                expected_version=version,
                allowed_context_refs=frozenset(),
            )
