"""Exercise the provider schema and the response-to-finalization boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import jsonschema
import pytest
from armi_cognition.api import CognitionSchemaDocument
from armi_kernel import load_yaml_file
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


_PURPOSE_KINDS = {
    "consider_creator_input": "no_change",
    "consider_life_query_result": "no_change",
    "consider_requested_visual_observation": "no_change",
    "consider_creator_outreach": "no_action",
    "consider_other_human_input": "silence",
    "consider_autonomous_life": "no_activity",
    "consider_activity_attention": "no_action",
    "consider_activity_internal_work": "no_result",
    "consider_sleep": "stay_awake",
    "consider_visual_observation": "ignore",
    "maintain_subjective_memory": "memory_unchanged",
    "perform_subject_self_check": "no_issue",
    "reflect_self": "no_change",
    "reflect_mind": "no_change",
    "reflect_mood": "no_change",
    "reflect_prompt": "no_change",
    "consider_codex_result": "no_change",
    "consider_codex_task": "no_change",
    "consider_web_evidence": "no_change",
}


def test_every_configured_purpose_is_in_contract_regression():
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    assert set(manifest["purpose_profiles"]) == set(_PURPOSE_KINDS)


@pytest.mark.parametrize("purpose", _PURPOSE_KINDS)
def test_each_purpose_schema_and_parser_accept_its_unchanged_decision(purpose):
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    version = manifest["purpose_profiles"][purpose]["response_contract_version"]
    kind = _PURPOSE_KINDS[purpose]
    value: dict[str, Any] = {"kind": kind}
    if version == "armi.creator-cognitive-act-candidate.v4":
        value = {
            "decision": {**value, "content": None},
            "experience": None,
            "appraisal": None,
            "changes": [],
        }
    elif purpose.startswith("reflect_"):
        value.update(
            target=purpose.removeprefix("reflect_"),
            summary="无需调整",
            basis_refs=[],
            expected_version=None,
            next_state=None,
        )
    elif purpose in {"maintain_subjective_memory", "perform_subject_self_check"}:
        value["summary"] = "无需调整"
    elif purpose == "consider_activity_internal_work":
        value.update(
            reason="资料暂缺",
            next_step="继续观察",
            resumption_cue="资料到达",
            review_after_seconds=60,
            appraisal=None,
        )
    elif purpose == "consider_creator_outreach":
        value.update(
            content=None,
            record_kind=None,
            query=None,
            source_kind=None,
            experience=None,
            changes=[],
        )
    elif purpose == "consider_other_human_input":
        value.update(experience=None, relationship_change=None, appraisal=None)
    elif purpose in {
        "consider_autonomous_life",
        "consider_activity_attention",
        "consider_visual_observation",
    }:
        value["appraisal"] = None
    elif version == "armi.cognition-candidate.v13":
        value = {
            "schema_version": version,
            "base": {
                "subject_version": 1,
                "state_epoch": 1,
                "bundle_activation_id": "01994200-0000-7000-8000-000000000001",
                "context_digest": "sha256:" + "0" * 64,
            },
            "disposition": kind,
            "understanding": {
                "text": "无需变化",
                "fact_class": "inference",
                "basis_refs": ["ctx:1"],
            },
            **{
                key: []
                for key in (
                    "experiences",
                    "component_changes",
                    "memory_changes",
                    "relationship_changes",
                    "activity_changes",
                    "action_choices",
                    "uncertainties",
                    "web_research_requests",
                    "visual_observation_requests",
                )
            },
            "reason_summary": "无需变化",
        }
    schema = _schema(version)
    jsonschema.validate({"candidate": value}, schema)
    parsed = parse_candidate(
        json.dumps(value, ensure_ascii=False).encode(),
        expected_version=version,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert parsed.schema_version == version


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
