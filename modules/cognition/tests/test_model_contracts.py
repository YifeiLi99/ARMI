"""ADP-MODEL and EVO-CONTRACT-MODEL offline contract checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import armi_cognition._model_contract as model_contract_module
import armi_cognition._other_human_contract as other_human_contract_module
import pytest
from armi_cognition._creator_cognitive_act_contract import CREATOR_COGNITIVE_ACT_VERSION
from armi_cognition._model_contract import (
    ACTIVE_MODEL_ID,
    ACTIVE_VERSION_POLICY,
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    MAINTENANCE_WORK_CANDIDATE_VERSION,
    CognitionCandidate,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    parse_candidate,
)
from armi_cognition._other_human_contract import (
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
)
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    ModelBinding,
    ModelViolation,
    PriceCatalog,
)
from armi_kernel.contracts import Digest

_BUNDLE_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
_PURPOSE_PROFILES = cast(
    dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml"))
)["purpose_profiles"]
_CONFIGURED_CANDIDATE_VERSIONS = sorted(
    {profile["response_contract_version"] for profile in _PURPOSE_PROFILES.values()}
)


@pytest.mark.parametrize(
    "change",
    [
        {"op": "relationship.interpret", "text": "我仍在了解对方。"},
        {"op": "relationship.fact", "text": "对方表达了一个偏好。"},
        {
            "op": "relationship.boundary",
            "party": "creator",
            "boundary": {"kind": "exit", "action": "end_contact"},
            "text": "对方要求结束接触。",
        },
        {
            "op": "commitment.establish",
            "party": "armi",
            "scope": "联系",
            "content": "联系前先询问。",
            "event_summary": "我作出了明确承诺。",
        },
        {"op": "commitment.withdraw", "target_ref": "ctx:1", "text": "撤回承诺。"},
        {
            "op": "material.create",
            "material_kind": "diary",
            "content": {"title": "记录", "body": "本次交流。"},
        },
    ],
)
def test_creator_current_changes_preserve_typed_fields(change) -> None:
    parsed = parse_candidate(
        {"decision": {"kind": "reply", "content": "回应"}, "changes": [change]},
        expected_version=CREATOR_COGNITIVE_ACT_VERSION,
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    assert parsed.model_dump(mode="json", exclude_unset=True)["changes"] == [change]


@pytest.mark.parametrize(
    "extra",
    [
        {"self_change": {"name": {"value": "模型命名"}}},
        {"mind_change": {"goals": {"values": ["模型目标"]}}},
        {"memory_change": {"action": "forget", "memory_ref": "ctx:1"}},
        {"subject_prompt_change": {"cognition_method": "模型改写"}},
        {"experience": {"first_person_gist": "经历", "source_kind": "experienced"}},
        {"changes": [{"op": "codex.request", "target_ref": "ctx:1"}]},
        {"changes": [{"op": "commitment.fulfill", "text": "缺少引用"}]},
        {
            "changes": [
                {
                    "op": "relationship.boundary",
                    "party": "armi",
                    "boundary": {"kind": "contact", "action": "end_contact"},
                    "text": "错误边界",
                }
            ]
        },
    ],
)
def test_creator_current_contract_rejects_removed_or_forged_fields(extra) -> None:
    with pytest.raises(ModelViolation):
        parse_candidate(
            {"decision": {"kind": "reply", "content": "回应"}, **extra},
            expected_version=CREATOR_COGNITIVE_ACT_VERSION,
            allowed_context_refs=frozenset({"ctx:1"}),
        )


def test_internal_candidate_parser_error_is_not_reported_as_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_value: object) -> object:
        raise RuntimeError("internal parser defect")

    monkeypatch.setattr(model_contract_module, "strict_model_value", fail)
    with pytest.raises(RuntimeError, match="internal parser defect"):
        parse_candidate(b"{}", allowed_context_refs=frozenset())


def test_internal_other_human_parser_error_is_not_reported_as_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_value: object) -> object:
        raise RuntimeError("internal other-human parser defect")

    monkeypatch.setattr(other_human_contract_module, "strict_model_value", fail)
    with pytest.raises(RuntimeError, match="internal other-human parser defect"):
        other_human_contract_module.parse_other_human_dialogue_candidate_value(
            {}, allowed_context_refs=frozenset()
        )


def test_other_human_instructions_require_relationship_interpretation() -> None:
    assert "填写关系事实、边界或承诺变化时" in OTHER_HUMAN_DIALOGUE_INSTRUCTIONS
    assert (
        "experience 和非空 relationship_interpretation"
        in OTHER_HUMAN_DIALOGUE_INSTRUCTIONS
    )
    assert "理解未变时可保留原解释" in OTHER_HUMAN_DIALOGUE_INSTRUCTIONS


def test_other_human_social_contract_versions_relationship_context_refs() -> None:
    current = parse_candidate(
        json.dumps(
            {
                "decision": {"kind": "silence"},
                "social": {
                    "experience": {"first_person_gist": "对方明确改变了承诺。"},
                    "relationship_change": {
                        "commitment_change": {
                            "action": "violate",
                            "commitment_ref": "ctx:3",
                            "event_summary": "对方确认没有履行承诺。",
                        }
                    },
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset({"ctx:3"}),
        expected_version=OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    )
    assert getattr(current, "relationship_change", None) is not None
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(
                {
                    "decision": {"kind": "silence"},
                    "social": {
                        "experience": {"first_person_gist": "对方改变了承诺。"},
                        "relationship_change": {
                            "commitment_change": {
                                "action": "violate",
                                "commitment_ref": "ctx:4",
                                "event_summary": "对方没有履行承诺。",
                            }
                        },
                    },
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset({"ctx:3"}),
            expected_version=OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
        )

    current = json.dumps(
        other_human_contract_module.candidate_schema(
            OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
        )
    )
    assert "concerns" in current
    assert "suddenness" not in current


def test_autonomous_activity_contract_is_strict_and_character_bounded() -> None:
    parsed = parse_candidate(
        b'{"kind":"start_activity","goal":"learn","next_step":"read","next_consideration_seconds":60}',
        allowed_context_refs=frozenset(),
        expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "start_activity"
    assert set(candidate_schema(AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION)) >= {
        "$defs",
        "discriminator",
    }

    for value in (
        b'{"kind":"start_activity","goal":"learn","next_step":"read","status":"ready","next_consideration_seconds":60}',
        json.dumps(
            {
                "kind": "start_activity",
                "goal": "界" * 2049,
                "next_step": "read",
                "next_consideration_seconds": 60,
            }
        ).encode(),
    ):
        with pytest.raises(ModelViolation):
            parse_candidate(
                value,
                allowed_context_refs=frozenset(),
                expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
            )


def test_removed_activity_contracts_are_not_executable() -> None:
    for version in (
        "armi.activity-attention-candidate.v5",
        "armi.activity-internal-work-candidate.v5",
    ):
        with pytest.raises(ModelViolation, match="MODEL-BINDING"):
            candidate_schema(version)
        with pytest.raises(ModelViolation):
            parse_candidate(
                b'{"kind":"engage"}',
                allowed_context_refs=frozenset(),
                expected_version=version,
            )


def test_autonomous_activity_progress_preserves_materials_and_schedule() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "progress",
                "progress_summary": "formed a real outline",
                "next_consideration_seconds": 60,
                "next_step": "review one section later",
                "material_change": {
                    "action": "create",
                    "material_kind": "draft",
                    "title": "outline",
                    "body": "A real bounded draft.",
                    "metadata": {},
                    "material_status": "active",
                },
            }
        ).encode(),
        allowed_context_refs=frozenset(),
        expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "progress"
    schema_text = json.dumps(
        candidate_schema(AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION),
        separators=(",", ":"),
    )
    assert "material_change" in schema_text
    assert "activity_id" not in schema_text
    binding = load_purpose_binding("consider_autonomous_life")
    assert binding.profile == "autonomous_activity"
    assert binding.response_contract_version == AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION
    assert binding.output_token_limit == 4096

    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(
                {
                    "kind": "no_result",
                    "reason": "nothing reliable",
                    "next_step": "retry later",
                    "resumption_cue": "scheduled review",
                    "next_consideration_seconds": 1,
                }
            ).encode(),
            allowed_context_refs=frozenset(),
            expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
        )


def test_maintenance_work_contract_is_phase_bounded_and_context_referenced() -> None:
    unchanged = parse_candidate(
        b'{"kind":"memory_unchanged","summary":"No grounded change is needed."}',
        allowed_context_refs=frozenset(),
        expected_version=MAINTENANCE_WORK_CANDIDATE_VERSION,
    )
    assert getattr(unchanged, "kind", None) == "memory_unchanged"
    binding = load_purpose_binding("maintain_subjective_memory")
    assert binding.profile == "memory_maintenance"
    assert binding.response_contract_version == MAINTENANCE_WORK_CANDIDATE_VERSION
    assert load_purpose_binding("perform_subject_self_check").profile == (
        "subject_self_check"
    )

    schema_text = json.dumps(
        candidate_schema(MAINTENANCE_WORK_CANDIDATE_VERSION), separators=(",", ":")
    )
    assert "consolidate" in schema_text
    assert "issue_found" in schema_text
    assert "audit" not in schema_text
    assert "relationship_change" not in schema_text

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-REFERENCE"):
        parse_candidate(
            json.dumps(
                {
                    "kind": "reinterpret",
                    "memory_ref": "ctx:2",
                    "reason": "A current contradiction changes the interpretation.",
                    "summary": "A revised current understanding.",
                }
            ).encode(),
            allowed_context_refs=frozenset({"ctx:1"}),
            expected_version=MAINTENANCE_WORK_CANDIDATE_VERSION,
        )


def _candidate() -> dict[str, object]:
    return {
        "schema_version": "armi.cognition-candidate.v17",
        "base": {
            "subject_version": 0,
            "state_epoch": 0,
            "bundle_activation_id": str(uuid7()),
            "context_digest": Digest.from_bytes(b"context").value,
        },
        "disposition": "no_change",
        "understanding": {
            "text": "The current external claim does not require a change.",
            "fact_class": "external_claim",
            "basis_refs": ["ctx:1"],
        },
        "experiences": [],
        "component_changes": [],
        "memory_changes": [],
        "relationship_changes": [],
        "activity_changes": [],
        "action_choices": [],
        "uncertainties": [],
        "reason_summary": "No proposal is warranted by the provided context.",
    }


def _dialogue_candidate() -> dict[str, object]:
    return {
        "kind": "reply",
        "content": "Hello, I am here.",
        "changes": [],
    }


@pytest.mark.parametrize("version", _CONFIGURED_CANDIDATE_VERSIONS)
@pytest.mark.parametrize("offset", [-1, 1])
def test_candidate_schema_and_parser_reject_other_contract_versions(version, offset):
    family, number = version.rsplit(".v", 1)
    unsupported = f"{family}.v{int(number) + offset}"
    assert candidate_schema(version)
    with pytest.raises(ModelViolation, match="MODEL-BINDING"):
        candidate_schema(unsupported)
    # A valid generic candidate must not bypass the selected contract version.
    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            json.dumps(_candidate()).encode(),
            allowed_context_refs=frozenset({"ctx:1"}),
            expected_version=unsupported,
        )


@pytest.mark.parametrize("offset", [-1, 1])
def test_candidate_wire_rejects_other_schema_versions(offset):
    value = _candidate()
    version = str(value["schema_version"])
    parsed = parse_candidate(
        json.dumps(value).encode(), allowed_context_refs=frozenset({"ctx:1"})
    )
    assert parsed.schema_version == version
    family, number = version.rsplit(".v", 1)
    value["schema_version"] = f"{family}.v{int(number) + offset}"
    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            json.dumps(value).encode(), allowed_context_refs=frozenset({"ctx:1"})
        )


@pytest.mark.parametrize("purpose", sorted(_PURPOSE_PROFILES))
def test_purpose_binding_rejects_previous_contract_version(tmp_path: Path, purpose):
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    profile = manifest["purpose_profiles"][purpose]
    family, number = profile["response_contract_version"].rsplit(".v", 1)
    profile["response_contract_version"] = f"{family}.v{int(number) - 1}"
    path = tmp_path / "model-bindings.yaml"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)


def _request(binding: ModelBinding):
    context = json.dumps(
        {
            "schema_version": "armi.compiled-context.v3",
            "purpose": "consider_creator_input",
            "layers": [
                {
                    "layer": "stable_prefix",
                    "items": [],
                },
                {"layer": "scope_context", "items": []},
                {"layer": "conversation_history", "items": []},
                {
                    "layer": "turn_tail",
                    "items": [
                        {
                            "section": "mood",
                            "item_kind": "mood",
                            "source": {
                                "kind": "subjective_mood",
                                "reference": "01980f7d-7b8f-7e2a-8a11-2ab8e123456a",
                                "version": 1,
                                "digest": Digest.from_bytes(b"calm").value,
                            },
                            "trust": "subjective_state",
                            "privacy": "private",
                            "content": json.dumps(
                                {"description": "我现在很平静。"},
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "section": "memory",
                            "item_kind": "recent_experience",
                            "source": {
                                "kind": "accepted_experience",
                                "reference": "01980f7d-7b8f-7e2a-8a11-2ab8e1234567",
                                "version": 1,
                                "digest": Digest.from_bytes(b"recent").value,
                            },
                            "trust": "subjective_state",
                            "privacy": "private",
                            "content": json.dumps(
                                {"first_person_gist": "之前我听到过相近的事情。"},
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "section": "evidence",
                            "item_kind": "current_evidence",
                            "source": {
                                "kind": "creator_input",
                                "reference": "01980f7d-7b8f-7e2a-8a11-2ab8e1234568",
                                "version": 3,
                                "digest": Digest.from_bytes(b"hello").value,
                            },
                            "trust": "external_claim",
                            "privacy": "private",
                            "content": json.dumps(
                                {
                                    "message_id": "01980f7d-7b8f-7e2a-8a11-2ab8e1234569",
                                    "text": "Hello",
                                }
                            ),
                        },
                    ],
                },
            ],
        },
        separators=(",", ":"),
    ).encode()
    context_digest = Digest.from_bytes(context)
    request_bytes = build_request_bytes(
        binding=binding,
        compiled_context=context,
        context_digest=context_digest,
        base_subject_version=0,
        base_state_epoch=0,
        bundle_activation_id=_BUNDLE_ID,
        included_context_refs=(
            {"ref": "ctx:1", "section": "mood", "item_kind": "mood"},
            {
                "ref": "ctx:2",
                "section": "memory",
                "item_kind": "recent_experience",
            },
            {"ref": "ctx:3", "section": "evidence", "item_kind": "current_evidence"},
        ),
    )
    return checked_model_request(
        prices=PriceCatalog(()),
        binding=binding,
        request_bytes=request_bytes,
        context_digest=context_digest,
        input_tokens=128,
    )


def test_only_evolving_binding_is_active_and_request_is_stable() -> None:
    first = load_active_binding()
    second = load_active_binding()
    assert first.model_id == ACTIVE_MODEL_ID == "qwen3.8-flash"
    assert first.version_policy == ACTIVE_VERSION_POLICY
    assert first.response_model_identity_required
    assert first == second
    assert _request(first).canonical_bytes == _request(second).canonical_bytes


def test_creator_dialogue_uses_compact_purpose_contract() -> None:
    active = load_active_binding()
    dialogue = load_purpose_binding("consider_creator_input")
    assert dialogue.model_id == active.model_id == ACTIVE_MODEL_ID
    assert dialogue.profile == "creator_cognitive_act"
    assert (
        dialogue.response_contract_version == "armi.creator-cognitive-act-candidate.v7"
    )
    assert dialogue.output_token_limit == 2048

    request = json.loads(_request(dialogue).canonical_bytes)
    assert request["schema_version"] == "armi.model-request.v1"
    assert (
        request["output_contract"]["schema_version"]
        == "armi.creator-cognitive-act-candidate.v7"
    )
    assert request["candidate_base"]["bundle_activation_id"] == str(_BUNDLE_ID)


def test_codex_candidate_has_no_permission_request_contract() -> None:
    schema = candidate_schema()
    assert "capability_requests" not in schema["properties"]
    candidate = _candidate()
    candidate["capability_requests"] = []
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(candidate).encode(), allowed_context_refs=frozenset({"ctx:1"})
        )


def test_creator_dialogue_request_prioritizes_exact_recent_turns_and_local_refs() -> (
    None
):
    binding = load_purpose_binding("consider_creator_input")
    source_id = "01980f7d-7b8f-7e2a-8a11-2ab8e1234570"
    items = (
        (
            "runtime_truth",
            "runtime_identity",
            {"subject_id": source_id, "subject_version": 9},
            "runtime_authority",
        ),
        (
            "memory",
            "current_memory",
            {
                "memory_id": source_id,
                "summary": "我们曾经聊过雨声。",
                "uncertainty": None,
                "links": [],
            },
            "subjective_state",
        ),
        (
            "scene",
            "recent_scene_turn",
            {"speaker": "armi", "text": "这是缺少前置 Creator 原话的半轮回复。"},
            "runtime_authority",
        ),
        (
            "scene",
            "recent_scene_turn",
            {"speaker": "creator", "text": "窗外的光很好看。"},
            "external_claim",
        ),
        (
            "scene",
            "recent_scene_turn",
            {"speaker": "armi", "text": "我也想知道那片光落在哪里。"},
            "runtime_authority",
        ),
        (
            "activity",
            "current_activity",
            {"activities": []},
            "runtime_authority",
        ),
        (
            "capability",
            "capability_state_expired",
            {
                "capability_kind": "creator.scene.reply",
                "operation": "send",
                "availability_status": "available",
                "authorization_status": "expired",
                "effective_grant": {"remaining_uses": 0},
            },
            "runtime_authority",
        ),
        (
            "evidence",
            "current_evidence",
            "你想聊些什么?",
            "external_claim",
        ),
    )
    layer_names = (
        "stable_prefix",
        "scope_context",
        "conversation_history",
        "turn_tail",
    )
    layer_items: dict[str, list[dict[str, object]]] = {
        layer: [] for layer in layer_names
    }
    refs = []
    for section, kind, content, trust in items:
        layer = (
            "stable_prefix"
            if kind == "runtime_identity"
            else "conversation_history"
            if kind == "recent_scene_turn"
            else "turn_tail"
        )
        layer_items[layer].append(
            {
                "section": section,
                "item_kind": kind,
                "source": {
                    "kind": kind,
                    "reference": source_id,
                    "version": 1,
                    "digest": Digest.from_bytes(kind.encode()).value,
                },
                "trust": trust,
                "privacy": "private",
                "content": json.dumps(content, ensure_ascii=False),
            }
        )
    for layer in layer_names:
        for item in layer_items[layer]:
            refs.append(
                {
                    "ref": f"ctx:{len(refs) + 1}",
                    "section": item["section"],
                    "item_kind": item["item_kind"],
                }
            )
    compiled = json.dumps(
        {
            "schema_version": "armi.compiled-context.v3",
            "purpose": "consider_creator_input",
            "layers": [
                {"layer": layer, "items": layer_items[layer]} for layer in layer_names
            ],
        },
        ensure_ascii=False,
    ).encode()
    request = json.loads(
        build_request_bytes(
            binding=binding,
            compiled_context=compiled,
            context_digest=Digest.from_bytes(compiled),
            base_subject_version=9,
            base_state_epoch=4,
            bundle_activation_id=_BUNDLE_ID,
            included_context_refs=tuple(refs),
        )
    )

    assert request["compiled_context"] == json.loads(compiled)
    assert request["included_context_refs"] == refs
    assert request["context_digest"] == Digest.from_bytes(compiled).value
    assert request["candidate_base"]["subject_version"] == 9
    assert request["output_contract"]["schema_version"] == (
        "armi.creator-cognitive-act-candidate.v7"
    )


def test_other_human_dialogue_uses_the_shared_frozen_request() -> None:
    binding = load_purpose_binding("consider_other_human_input")
    source_id = "01980f7d-7b8f-7e2a-8a11-2ab8e1234571"
    compiled = json.dumps(
        {
            "schema_version": "armi.compiled-context.v3",
            "purpose": "consider_other_human_input",
            "layers": [
                {"layer": "stable_prefix", "items": []},
                {"layer": "scope_context", "items": []},
                {
                    "layer": "conversation_history",
                    "items": [
                        {
                            "section": "scene",
                            "item_kind": "recent_scene_turn",
                            "source": {
                                "kind": "turn",
                                "reference": source_id,
                                "version": 1,
                            },
                            "trust": "external_claim",
                            "privacy": "private",
                            "content": json.dumps(
                                {"speaker": "other_human", "text": "之前的问题"},
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "section": "scene",
                            "item_kind": "recent_scene_turn",
                            "source": {
                                "kind": "turn",
                                "reference": source_id,
                                "version": 2,
                            },
                            "trust": "runtime_authority",
                            "privacy": "private",
                            "content": json.dumps(
                                {"speaker": "armi", "text": "之前的回答"},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
                {
                    "layer": "turn_tail",
                    "items": [
                        {
                            "section": "evidence",
                            "item_kind": "current_evidence",
                            "source": {
                                "kind": "qq_input",
                                "reference": source_id,
                                "version": 3,
                            },
                            "trust": "external_claim",
                            "privacy": "private",
                            "content": "现在的问题",
                        }
                    ],
                },
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()

    request = json.loads(
        build_request_bytes(
            binding=binding,
            compiled_context=compiled,
            context_digest=Digest.from_bytes(compiled),
            base_subject_version=2,
            base_state_epoch=1,
            bundle_activation_id=_BUNDLE_ID,
            included_context_refs=tuple(
                {
                    "ref": f"ctx:{ordinal}",
                    "section": section,
                    "item_kind": item_kind,
                }
                for ordinal, (section, item_kind) in enumerate(
                    (
                        ("scene", "recent_scene_turn"),
                        ("scene", "recent_scene_turn"),
                        ("evidence", "current_evidence"),
                    ),
                    1,
                )
            ),
        )
    )

    assert binding.response_contract_version == OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION
    assert request["schema_version"] == "armi.model-request.v1"
    assert request["compiled_context"] == json.loads(compiled)
    assert [ref["ref"] for ref in request["included_context_refs"]] == [
        "ctx:1",
        "ctx:2",
        "ctx:3",
    ]


@pytest.mark.parametrize(
    "purpose",
    [
        "consider_creator_outreach",
        "consider_activity_attention",
        "consider_activity_internal_work",
    ],
)
def test_replaced_autonomy_purposes_have_no_executable_binding(purpose: str) -> None:
    with pytest.raises(ModelViolation, match="MODEL-BINDING"):
        load_purpose_binding(purpose)


def test_web_dialogue_uses_current_action_contract_and_rejects_url_fields() -> None:
    schema = candidate_schema(CREATOR_COGNITIVE_ACT_VERSION)
    schema_text = json.dumps(schema, separators=(",", ":"))
    assert '"web_research"' in schema_text
    assert '"schema_version"' not in schema_text
    assert '"subject_id"' not in schema_text

    parsed = parse_candidate(
        json.dumps(
            {
                "decision": {
                    "kind": "web_research",
                    "query": "PostgreSQL 18 正式发布说明",
                }
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
        expected_version=CREATOR_COGNITIVE_ACT_VERSION,
    )
    assert parsed.schema_version == CREATOR_COGNITIVE_ACT_VERSION
    assert parsed.model_dump(mode="json")["decision"] == {
        "kind": "web_research",
        "query": "PostgreSQL 18 正式发布说明",
    }

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            b'{"decision":{"kind":"web_research","url":"https://example.com/"}}',
            allowed_context_refs=frozenset(),
            expected_version=CREATOR_COGNITIVE_ACT_VERSION,
        )


def test_dialogue_exact_life_query_schema_excludes_logs_and_admin_data() -> None:
    schema_text = json.dumps(candidate_schema(CREATOR_COGNITIVE_ACT_VERSION))
    assert '"exact_life_query"' in schema_text
    assert '"self_change"' in schema_text
    assert '"audit"' not in schema_text
    assert '"credential"' not in schema_text

    parsed = parse_candidate(
        json.dumps(
            {
                "decision": {
                    "kind": "exact_life_query",
                    "record_kind": "material",
                    "query": "我的私人草稿",
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
        expected_version=CREATOR_COGNITIVE_ACT_VERSION,
    )
    assert parsed.schema_version == CREATOR_COGNITIVE_ACT_VERSION
    assert parsed.model_dump(mode="json")["decision"] == {
        "kind": "exact_life_query",
        "record_kind": "material",
        "query": "我的私人草稿",
    }

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            b'{"decision":{"kind":"exact_life_query","record_kind":"audit","query":"logs"}}',
            allowed_context_refs=frozenset(),
            expected_version=CREATOR_COGNITIVE_ACT_VERSION,
        )


def test_manifest_rejects_a_second_binding_or_fixed_model(tmp_path: Path) -> None:
    source = Path("configs/model-bindings.yaml")
    manifest = cast(dict[str, Any], load_yaml_file(source))
    manifest["bindings"].append(dict(manifest["bindings"][0]))
    path = tmp_path / "model-bindings.yaml"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)


def test_creator_manifest_rejects_unsupported_cognitive_act_contract(
    tmp_path: Path,
) -> None:
    source = Path("configs/model-bindings.yaml")
    manifest = cast(dict[str, Any], load_yaml_file(source))
    manifest["purpose_profiles"]["consider_creator_input"][
        "response_contract_version"
    ] = "armi.creator-dialogue-candidate.unsupported"
    path = tmp_path / "model-bindings.yaml"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)
    manifest["bindings"] = [manifest["bindings"][0]]
    manifest["bindings"][0]["model_id"] = "doubao-seed-2-1-turbo-260628"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)


def test_candidate_rejects_unknown_or_unavailable_context_reference() -> None:
    value = _candidate()
    value["experiences"] = [
        {
            "proposal_ref": "proposal:1",
            "atomic_group_ref": "group:1",
            "basis_refs": ["ctx:2"],
            "payload": {
                "proposal_kind": "experiences",
                "fact_class": "external_claim",
                "first_person_gist": "I received an ungrounded claim.",
                "source_perspective": "creator_claim",
                "uncertainty": "The basis is unavailable.",
                "privacy_scope": "private",
            },
        }
    ]
    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-REFERENCE"):
        parse_candidate(
            json.dumps(value).encode(),
            allowed_context_refs=frozenset({"ctx:1"}),
        )


def test_codex_observation_may_omit_nullable_uncertainty() -> None:
    value = _candidate()
    value["disposition"] = "change"
    value["experiences"] = [
        {
            "proposal_ref": "proposal:1",
            "atomic_group_ref": "group:1",
            "basis_refs": ["ctx:1"],
            "payload": {
                "proposal_kind": "experiences",
                "fact_class": "external_claim",
                "first_person_gist": "I observed the verified Codex result.",
                "source_perspective": "codex_observation",
                "privacy_scope": "private",
            },
        }
    ]

    parsed = parse_candidate(
        json.dumps(value).encode(),
        allowed_context_refs=frozenset({"ctx:1"}),
    )

    assert isinstance(parsed, CognitionCandidate)
    assert parsed.experiences[0].payload.uncertainty is None
