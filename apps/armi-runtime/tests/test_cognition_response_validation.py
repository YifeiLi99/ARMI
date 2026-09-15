"""Exercise the provider schema and the response-to-finalization boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import jsonschema
import pytest
from armi_cognition.api import CognitionSchemaDocument
from armi_kernel.application import ModelResultStatus, ModelViolation
from armi_runtime.adapters.model.volcengine_ark import (
    VolcengineArkModelAdapter,
    _provider_output_schema,
)
from armi_runtime.composition.model_verification import (
    candidate_schema,
    load_active_binding,
    parse_candidate,
)


def _schema(version):
    return _provider_output_schema(candidate_schema(version), available_refs=("ctx:1",))


def test_creator_schema_is_smaller_without_repeating_the_complete_object():
    schema = _schema("armi.creator-cognitive-act-candidate.v4")
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) < 12251
    assert schema["properties"]["candidate"]["type"] == "object"
    assert "decision" in schema["properties"]["candidate"]["properties"]
    assert "experience" in schema["properties"]["candidate"]["properties"]


@pytest.mark.parametrize("kind", ["no_change", "update"])
def test_reflection_keeps_evidence_without_requiring_a_change(kind):
    value = {
        "kind": kind,
        "target": "mood",
        "summary": "No adjustment needed.",
        "basis_refs": ["ctx:1"],
        "expected_version": 1 if kind == "update" else None,
        "next_state": {} if kind == "update" else None,
    }
    version = "armi.owner-reflection-candidate.v2"
    jsonschema.validate({"candidate": value}, _schema(version))
    parsed = parse_candidate(
        json.dumps(value).encode(),
        expected_version=version,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert parsed.model_dump(mode="json")["basis_refs"] == ["ctx:1"]


@pytest.mark.parametrize("invalid", [False, True])
def test_reply_memory_shape_is_visible_to_provider(invalid):
    value = {
        "decision": {"kind": "reply", "content": "Hello"},
        "experience": {
            "first_person_gist": "A greeting",
            "uncertainty": None,
            "memory_summary": 42 if invalid else None,
        },
        "appraisal": None,
        "changes": [],
    }
    schema = _schema("armi.creator-cognitive-act-candidate.v4")
    if invalid:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"candidate": value}, schema)
    else:
        jsonschema.validate({"candidate": value}, schema)


@pytest.mark.parametrize("kind", ["fade", "forget", "consolidate", "reinterpret"])
def test_maintenance_summary_matches_operation(kind):
    value = {
        "kind": kind,
        "memory_ref": "ctx:1",
        "reason": "Changed relevance",
        "summary": "Replacement" if kind == "reinterpret" else None,
        "uncertainty": None,
        "relation": None,
    }
    schema = _schema("armi.maintenance-work-candidate.v2")
    jsonschema.validate({"candidate": value}, schema)
    value["summary"] = None if kind == "reinterpret" else "Unexpected replacement"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, schema)


@pytest.mark.parametrize("transition", ["new", "reinforce", "reappraise", "resolve"])
def test_appraisal_reference_and_trajectory_are_part_of_schema(transition):
    appraisal = {
        "trajectory": {"transition": "new"}
        if transition == "new"
        else {
            "transition": transition,
            "episode_ref": "ctx:1",
            "change_from_previous": "improved",
        },
        "event_phase": "realized",
        "gist": "Greeting",
        "basis_refs": ["ctx:1"],
        "appraisal": {
            "concerns": [
                {
                    "target": "relationship",
                    "significance": "direct",
                    "direction": "progress",
                }
            ],
            "expectedness": "expected",
            "outcome_certainty": "settled",
            "intrinsic_quality": "pleasant",
            "self_involvement": "limited",
            "demand": None,
            "causality": None,
            "coping": None,
            "standards": {
                "self_evaluation": {"compatibility": "aligned"},
                "norm_compatibility": "aligned",
            },
        },
    }
    value = {
        "decision": {"kind": "reply", "content": "Hello"},
        "experience": None,
        "appraisal": appraisal,
        "changes": [],
    }
    version = "armi.creator-cognitive-act-candidate.v4"
    schema = _schema(version)
    jsonschema.validate({"candidate": value}, schema)
    parse_candidate(
        json.dumps(value).encode(),
        expected_version=version,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    appraisal["trajectory"]["episode_ref"] = "ctx:1" if transition == "new" else None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, schema)
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            allowed_context_refs=frozenset({"ctx:1"}),
        )


@pytest.mark.parametrize(
    "output",
    [
        '{"candidate":{"kind":"reply","content":"Hello"}}',
        '{"candidate":{"kind":"reply","content":42}}',
        "invalid json",
    ],
)
def test_returned_output_is_saved_before_local_rejection(output):
    binding = replace(
        load_active_binding(),
        response_contract_version="armi.creator-cognitive-act-candidate.v4",
    )
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=Mock(),
        locator=Mock(),
        candidate_schema=CognitionSchemaDocument(
            json.dumps(candidate_schema(binding.response_contract_version)).encode()
        ),
        instructions="",
        schema_name="test",
        transport=Mock(),
    )
    result = adapter._settle_response(
        {
            "provider_request_id": "test-request",
            "model_id": "doubao-seed-evolving",
            "output_text": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 0},
            "raw": {"output": [{"type": "message"}]},
        },
        cast(Any, SimpleNamespace(canonical_bytes=b'{"available_refs":[]}')),
    )
    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.response_bytes is not None
    saved = json.loads(result.response_bytes)
    assert saved["output_text"] == output
    assert saved["schema_version"] == "armi.model-response-artifact.v3"
    assert "candidate" not in saved
    assert "validation_error" not in saved
