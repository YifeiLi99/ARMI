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
from armi_cognition.api import CognitionSchemaDocument, parse_autonomy_check
from armi_kernel import load_yaml_file
from armi_kernel.application import ModelResultStatus, ModelViolation
from armi_runtime.adapters.model.structured import (
    _provider_output_schema,
)
from armi_runtime.composition.model_adapter import create_model_adapter
from armi_runtime.composition.model_verification import (
    bind_context_schema,
    candidate_schema,
    load_active_binding,
    parse_candidate,
)


def _schema(version, purpose=None):
    return _provider_output_schema(
        candidate_schema(version, purpose=purpose), available_refs=("ctx:1",)
    )


_PURPOSE_KINDS = {
    "consider_autonomy_check": "wait",
    "consider_creator_input": "no_change",
    "consider_life_query_result": "no_change",
    "consider_requested_visual_observation": "no_change",
    "consider_other_human_input": "silence",
    "consider_autonomous_life": "no_activity",
    "consider_sleep": "stay_awake",
    "consider_visual_observation": "ignore",
    "maintain_subjective_memory": "memory_unchanged",
    "perform_subject_self_check": "no_issue",
    "reflect_self": "no_change",
    "reflect_mind": "no_change",
    "reflect_prompt": "no_change",
    "consider_codex_result": "no_change",
    "consider_codex_task": "no_change",
}


def test_every_configured_purpose_is_in_contract_regression():
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    assert set(manifest["purpose_profiles"]) == set(_PURPOSE_KINDS)


@pytest.mark.parametrize("purpose", _PURPOSE_KINDS)
def test_each_purpose_schema_and_parser_accept_its_unchanged_decision(purpose):
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    version = manifest["purpose_profiles"][purpose]["response_contract_kind"]
    kind = _PURPOSE_KINDS[purpose]
    value: dict[str, Any] = {"kind": kind}
    if purpose == "consider_autonomy_check":
        value = {"engage": False}
        jsonschema.validate(value, candidate_schema(version))
        assert parse_autonomy_check(value).engage is False
        return
    if version == "armi.creator-cognitive-act-candidate":
        value = {
            "decision": {**value, "content": None},
            "experience": None,
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
        value = {
            "decision": {**value, "content": None},
            "experience": None,
            "changes": [],
        }
    elif purpose == "consider_other_human_input":
        value = {
            "decision": {**value, "content": None},
            "social": None,
        }
    elif purpose in {
        "consider_autonomous_life",
        "consider_visual_observation",
    }:
        if purpose == "consider_autonomous_life":
            value["expression"] = None
            value["mind_change"] = None
    elif version == "armi.cognition-candidate":
        value = {
            "schema_kind": version,
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
                    "visual_observation_requests",
                )
            },
            "reason_summary": "无需变化",
        }
    schema = _schema(version, purpose)
    if "concern_changes" in schema["properties"]["candidate"].get(
        "properties", {}
    ) or version in {
        "armi.autonomous-activity-candidate",
        "armi.visual-observation-candidate",
    }:
        value["concern_changes"] = []
        value["mind_appraisals"] = []
    jsonschema.validate({"candidate": value}, schema)
    parsed = parse_candidate(
        json.dumps(value, ensure_ascii=False).encode(),
        expected_version=version,
        purpose=purpose,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert parsed.schema_kind == version


@pytest.mark.parametrize("missing_experience", [True, False])
def test_other_human_social_dependencies_are_structural(missing_experience):
    version = "armi.other-human-dialogue-candidate"
    social = {
        "experience": {
            "first_person_gist": "We discussed our relationship.",
            "uncertainty": None,
        },
        "relationship_change": {
            "interpretation": None,
            "fact": None,
            "boundary": None,
            "commitment_change": None,
        },
    }
    if missing_experience:
        social["experience"] = None
        social["relationship_change"]["interpretation"] = "We are getting acquainted."
    value = {
        "decision": {"kind": "silence", "content": None},
        "social": social,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, _schema(version))
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            allowed_context_refs=frozenset(),
        )


@pytest.mark.parametrize("purpose", ["reflect_self", "reflect_mind", "reflect_prompt"])
def test_reflection_schema_excludes_other_owner_targets(purpose):
    version = "armi.owner-reflection-candidate"
    target = purpose.removeprefix("reflect_")
    value = {
        "kind": "no_change",
        "target": "mind" if target != "mind" else "self",
        "summary": "unchanged",
        "basis_refs": [],
        "expected_version": None,
        "next_state": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, _schema(version, purpose))
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            purpose=purpose,
            allowed_context_refs=frozenset(),
        )


@pytest.mark.parametrize(
    "purpose,kind",
    [
        ("maintain_subjective_memory", "no_issue"),
        ("perform_subject_self_check", "memory_unchanged"),
    ],
)
def test_maintenance_schema_excludes_the_other_phase(purpose, kind):
    version = "armi.maintenance-work-candidate"
    value = {"kind": kind, "summary": "unchanged"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, _schema(version, purpose))
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            purpose=purpose,
            allowed_context_refs=frozenset(),
        )


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "reply", "content": "legacy"},
        {
            "schema_kind": "armi.creator-dialogue-candidate.v26",
            "kind": "reply",
            "content": "legacy",
        },
    ],
)
def test_old_dialogue_wire_cannot_select_an_execution_parser(value):
    with pytest.raises(ModelViolation):
        parse_candidate(json.dumps(value).encode(), allowed_context_refs=frozenset())


def test_provider_selects_action_before_generating_branch_payload():
    # Canonical storage sorts keys, so source declaration order does not survive.
    source = json.loads(
        json.dumps(
            candidate_schema("armi.creator-cognitive-act-candidate"), sort_keys=True
        )
    )
    schema = _provider_output_schema(source, available_refs=("ctx:1",))
    branches = schema["properties"]["candidate"]["properties"]["decision"]["anyOf"]
    for branch in branches:
        if "$ref" in branch:
            branch = schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]
        assert next(iter(branch["properties"])) == "kind"
        assert branch["required"][0] == "kind"
    assert next(iter(source["$defs"]["ReplyDecision"]["properties"])) == "content"


def test_creator_schema_is_smaller_without_repeating_the_complete_object():
    # Measure the actual model schema for the same ordinary input reference.
    # No existing concern, activity or emotional episode is present in this Context.
    schema = _provider_output_schema(
        bind_context_schema(
            candidate_schema("armi.creator-cognitive-act-candidate"),
            ({"ref": "ctx:1", "item_kind": "current_evidence"},),
        ),
        available_refs=("ctx:1",),
    )
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()
    original = json.dumps(
        candidate_schema("armi.creator-cognitive-act-candidate"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert len(encoded) < len(original)
    assert schema["properties"]["candidate"]["type"] == "object"
    assert "decision" in schema["properties"]["candidate"]["properties"]
    assert "experience" in schema["properties"]["candidate"]["properties"]


@pytest.mark.parametrize(
    "action",
    [
        "establish",
        "modify",
        "fulfill",
        "withdraw",
        "forget",
        "violate",
        "note_conflict",
    ],
)
@pytest.mark.parametrize("valid", [True, False])
def test_other_human_commitment_dependencies_are_visible_in_schema(action, valid):
    version = "armi.other-human-dialogue-candidate"
    commitment = {
        "action": action,
        "commitment_ref": None if action == "establish" else "ctx:1",
        "party": "armi" if action == "establish" else None,
        "scope": "沟通" if action in {"establish", "modify"} else None,
        "content": "我会说明进度" if action == "establish" else None,
        "conflicts_with_ref": "ctx:1" if action == "note_conflict" else None,
        "event_summary": "承诺发生变化",
    }
    if not valid:
        if action == "establish":
            commitment["party"] = None
        elif action == "modify":
            commitment["scope"] = None
        elif action == "note_conflict":
            commitment["conflicts_with_ref"] = None
        else:
            commitment["party"] = "armi"
    value = {
        "decision": {"kind": "reply", "content": "我会认真对待"},
        "social": {
            "experience": {"first_person_gist": "我们谈到了承诺", "uncertainty": None},
            "relationship_change": {
                "interpretation": None,
                "fact": None,
                "boundary": None,
                "commitment_change": commitment,
            },
        },
    }
    if valid:
        jsonschema.validate({"candidate": value}, _schema(version))
        parse_candidate(
            json.dumps(value).encode(),
            expected_version=version,
            allowed_context_refs=frozenset({"ctx:1"}),
        )
    else:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"candidate": value}, _schema(version))
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(value).encode(),
                expected_version=version,
                allowed_context_refs=frozenset({"ctx:1"}),
            )


@pytest.mark.parametrize("kind", ["no_change", "update"])
def test_reflection_keeps_evidence_without_requiring_a_change(kind):
    value = {
        "kind": kind,
        "target": "prompt",
        "summary": "No adjustment needed.",
        "basis_refs": ["ctx:1"],
        "expected_version": 1 if kind == "update" else None,
        "next_state": {
            "cognition_method": "Consider evidence",
            "expression_method": "Be clear",
            "reflection_method": "Review evidence",
        }
        if kind == "update"
        else None,
    }
    version = "armi.owner-reflection-candidate"
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
        "concern_changes": [],
        "mind_appraisals": [],
        "decision": {"kind": "reply", "content": "Hello"},
        "experience": {
            "first_person_gist": "A greeting",
            "uncertainty": None,
            "memory_summary": 42 if invalid else None,
        },
        "changes": [],
    }
    schema = _schema("armi.creator-cognitive-act-candidate")
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
    schema = _schema("armi.maintenance-work-candidate")
    jsonschema.validate({"candidate": value}, schema)
    value["summary"] = None if kind == "reinterpret" else "Unexpected replacement"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidate": value}, schema)


@pytest.mark.parametrize("transition", ["new", "reinforce", "reappraise", "resolve"])
def test_mood_trajectory_is_rejected_by_main_schema(transition):
    value = {
        "decision": {"kind": "reply", "content": "Hi"},
        "appraisal": {"trajectory": {"transition": transition}},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"candidate": value}, _schema("armi.creator-cognitive-act-candidate")
        )


@pytest.mark.parametrize(
    "output",
    [
        '{"candidate":{"kind":"reply","content":"Hello"}}',
        '{"candidate":{"kind":"reply","content":42}}',
        "invalid json",
    ],
)
@pytest.mark.parametrize("provider_status", ["completed", "incomplete", "failed", None])
def test_returned_output_is_saved_before_local_rejection(output, provider_status):
    binding = replace(
        load_active_binding(),
        response_contract_kind="armi.creator-cognitive-act-candidate",
    )
    adapter = create_model_adapter(
        binding=binding,
        credential_port=Mock(),
        locator=Mock(),
        candidate_schema=CognitionSchemaDocument(
            json.dumps(candidate_schema(binding.response_contract_kind)).encode()
        ),
        instructions="",
        schema_name="test",
        transport=Mock(),
    )
    result = adapter._settle_response(
        {
            "provider_request_id": "test-request",
            "model_id": binding.model_id,
            "output_text": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 0},
            "raw": {
                "status": provider_status,
                "output": []
                if provider_status == "incomplete"
                else [{"type": "message"}],
            },
        },
        cast(Any, SimpleNamespace(canonical_bytes=b'{"available_refs":[]}')),
    )
    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.usage is not None
    assert result.usage.input_tokens == 10
    if provider_status != "completed":
        assert result.response_error_code == (
            "MODEL-RESPONSE-INCOMPLETE"
            if provider_status == "incomplete"
            else "MODEL-PROVIDER-STATUS"
        )
    assert result.response_bytes is not None
    saved = json.loads(result.response_bytes)
    assert saved["output_text"] == output
    assert saved["schema_kind"] == "armi.model-response-artifact"
    assert "candidate" not in saved
    assert "validation_error" not in saved


def test_saved_request_contains_actual_provider_input_without_credentials():
    binding = load_active_binding()
    adapter = create_model_adapter(
        binding=binding,
        credential_port=Mock(),
        locator=Mock(),
        candidate_schema=CognitionSchemaDocument(
            json.dumps(candidate_schema(binding.response_contract_kind)).encode()
        ),
        instructions="本次系统指令",
        schema_name="test",
        transport=Mock(),
    )
    request = cast(
        Any,
        SimpleNamespace(
            canonical_bytes=json.dumps(
                {
                    "schema_kind": "armi.model-request",
                    "compiled_context": {
                        "purpose": "consider_creator_input",
                        "layers": [
                            {
                                "items": [
                                    {
                                        "item_kind": "current_evidence",
                                        "content": "当前问题",
                                    }
                                ]
                            }
                        ],
                    },
                    "included_context_refs": [{"ref": "ctx:1"}],
                }
            ).encode(),
            max_output_tokens=512,
        ),
    )
    saved = json.loads(adapter.request_evidence(request))
    assert saved["schema_kind"] == "armi.model-input-evidence"
    assert "canonical_request" not in saved
    assert saved["provider_request"]["instructions"].startswith(
        "# ARMI 本轮认知\n\n本次系统指令"
    )
    assert "当前问题" in saved["provider_request"]["input"][-1]["content"]
    assert "compiled_context" not in json.dumps(saved["provider_request"]["input"])
    assert "JSON Schema" in saved["provider_request"]["instructions"]
    assert saved["provider_request"]["max_output_tokens"] == 512
    assert cast(Mock, adapter._credential_port).mock_calls == []
