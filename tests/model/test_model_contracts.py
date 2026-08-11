"""ADP-MODEL and EVO-CONTRACT-MODEL offline contract checks."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid7

import armi_runtime.composition.model_contract as model_contract_module
import armi_runtime.composition.other_human_dialogue_candidate_contract as other_human_contract_module
import pytest
from armi_kernel.application import (
    CredentialLocator,
    ModelBinding,
    ModelResultStatus,
    ModelViolation,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.model.volcengine_ark import (
    ArkTransport,
    VolcengineArkModelAdapter,
    _provider_input,
    _strict_provider_schema,
)
from armi_runtime.composition.configuration import EnvironmentFileCredentialPort
from armi_runtime.composition.dialogue_candidate_contract import (
    DIALOGUE_MODEL_OUTPUT_VERSION,
    dialogue_model_output_schema,
)
from armi_runtime.composition.model_contract import (
    ACTIVE_MODEL_ID,
    ACTIVE_VERSION_POLICY,
    ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    DIALOGUE_CANDIDATE_VERSION,
    DIALOGUE_INSTRUCTIONS,
    MAINTENANCE_WORK_CANDIDATE_VERSION,
    WEB_DIALOGUE_CANDIDATE_VERSION,
    CognitionCandidateV7,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    parse_candidate,
)
from armi_runtime.composition.other_human_dialogue_candidate_contract import (
    HISTORICAL_OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    OTHER_HUMAN_DIALOGUE_INSTRUCTIONS,
)

_BUNDLE_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")


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


def test_other_human_instructions_require_first_relationship_interpretation() -> None:
    assert "首次为当前对方形成 relationship_change" in OTHER_HUMAN_DIALOGUE_INSTRUCTIONS
    assert "必须同时提供 interpretation" in OTHER_HUMAN_DIALOGUE_INSTRUCTIONS


def test_other_human_social_contract_versions_relationship_context_refs() -> None:
    current = parse_candidate(
        json.dumps(
            {
                "kind": "silence",
                "experience": {"first_person_gist": "对方明确改变了承诺。"},
                "relationship_change": {
                    "commitment_change": {
                        "action": "violate",
                        "commitment_ref": "ctx:3",
                        "event_summary": "对方确认没有履行承诺。",
                    }
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
                    "kind": "silence",
                    "experience": {"first_person_gist": "对方改变了承诺。"},
                    "relationship_change": {
                        "commitment_change": {
                            "action": "violate",
                            "commitment_ref": "ctx:4",
                            "event_summary": "对方没有履行承诺。",
                        }
                    },
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset({"ctx:3"}),
            expected_version=OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
        )

    historical = parse_candidate(
        b'{"kind":"reply","content":"historical"}',
        allowed_context_refs=frozenset(),
        expected_version=HISTORICAL_OTHER_HUMAN_DIALOGUE_CANDIDATE_VERSION,
    )
    assert getattr(historical, "content", None) == "historical"
    assert "relationship_change" in historical.model_dump(mode="json")


def test_autonomous_activity_contract_is_compact_strict_and_byte_bounded() -> None:
    parsed = parse_candidate(
        b'{"kind":"start_activity","goal":"learn","next_step":"read"}',
        allowed_context_refs=frozenset(),
        expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "start_activity"
    assert set(candidate_schema(AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION)) >= {
        "$defs",
        "discriminator",
    }

    for value in (
        b'{"kind":"start_activity","goal":"learn","next_step":"read","status":"ready"}',
        json.dumps(
            {"kind": "start_activity", "goal": "界" * 683, "next_step": "read"}
        ).encode(),
    ):
        with pytest.raises(ModelViolation):
            parse_candidate(
                value,
                allowed_context_refs=frozenset(),
                expected_version=AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
            )


def test_activity_attention_contract_rejects_authority_and_invalid_wait_shapes() -> (
    None
):
    parsed = parse_candidate(
        b'{"kind":"engage"}',
        allowed_context_refs=frozenset(),
        expected_version=ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "engage"
    schema_text = json.dumps(
        candidate_schema(ACTIVITY_ATTENTION_CANDIDATE_VERSION), separators=(",", ":")
    )
    assert "activity_id" not in schema_text
    assert '"failed"' not in schema_text

    invalid = (
        {"kind": "engage", "activity_id": str(uuid7())},
        {"kind": "progress", "progress_summary": "done", "next_step": "continue"},
        {"kind": "complete", "progress_summary": "done", "terminal_reason": "done"},
    )
    for value in invalid:
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(value).encode(),
                allowed_context_refs=frozenset(),
                expected_version=ACTIVITY_ATTENTION_CANDIDATE_VERSION,
            )


def test_activity_internal_work_contract_is_bounded_and_has_no_external_execution() -> (
    None
):
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "progress",
                "progress_summary": "formed a real outline",
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
        expected_version=ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "progress"
    schema_text = json.dumps(
        candidate_schema(ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION),
        separators=(",", ":"),
    )
    assert "material_change" in schema_text
    assert "web" not in schema_text
    assert "tool" not in schema_text
    assert "activity_id" not in schema_text
    binding = load_purpose_binding("consider_activity_internal_work")
    assert binding.profile == "activity_internal_work"
    assert binding.response_contract_version == ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION
    assert binding.output_token_limit == 4096

    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(
                {
                    "kind": "no_result",
                    "reason": "nothing reliable",
                    "next_step": "retry later",
                    "resumption_cue": "scheduled review",
                    "review_after_seconds": 1,
                }
            ).encode(),
            allowed_context_refs=frozenset(),
            expected_version=ACTIVITY_INTERNAL_WORK_CANDIDATE_VERSION,
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
        "schema_version": "armi.cognition-candidate.v7",
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
        "capability_requests": [],
        "action_choices": [],
        "uncertainties": [],
        "reason_summary": "No proposal is warranted by the provided context.",
    }


def _dialogue_candidate() -> dict[str, object]:
    return {
        "kind": "reply",
        "content": "Hello, I am here.",
    }


def _request(binding: ModelBinding):
    context = json.dumps(
        {
            "schema_version": "armi.compiled-context.v1",
            "purpose": "consider_creator_input",
            "sections": [
                {
                    "section": "evidence",
                    "items": [
                        {
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
                        }
                    ],
                }
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
            {"ref": "ctx:1", "section": "evidence", "item_kind": "current_evidence"},
        ),
    )
    return checked_model_request(
        binding=binding,
        request_bytes=request_bytes,
        context_digest=context_digest,
        input_tokens=128,
    )


def test_only_evolving_binding_is_active_and_request_is_stable() -> None:
    first = load_active_binding()
    second = load_active_binding()
    assert first.model_id == ACTIVE_MODEL_ID == "doubao-seed-evolving"
    assert first.version_policy == ACTIVE_VERSION_POLICY
    assert first.response_model_identity_required
    assert first.input_microyuan_per_million == 6_000_000
    assert first.output_microyuan_per_million == 30_000_000
    assert first == second
    assert _request(first).canonical_bytes == _request(second).canonical_bytes


def test_provider_dialogue_schema_is_strict_and_binds_runtime_refs() -> None:
    schema = _strict_provider_schema(
        dialogue_model_output_schema(web_search=False),
        available_refs=("ctx:1", "ctx:7"),
    )
    assert isinstance(schema, dict)

    def assert_strict(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                assert_strict(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert value.get("additionalProperties") is False
            assert value.get("required") == list(properties)
        for item in value.values():
            assert_strict(item)

    assert_strict(schema)
    encoded = json.dumps(schema, separators=(",", ":"))
    assert '"enum":["ctx:1","ctx:7"]' in encoded
    assert '"pattern":"^ctx:' not in encoded


def test_creator_dialogue_uses_compact_purpose_contract() -> None:
    legacy = load_active_binding()
    dialogue = load_purpose_binding("consider_creator_input")
    life_query_result = load_purpose_binding("consider_life_query_result")
    assert dialogue.model_id == legacy.model_id == ACTIVE_MODEL_ID
    assert dialogue.profile == "creator_dialogue"
    assert dialogue.response_contract_version == DIALOGUE_CANDIDATE_VERSION
    assert dialogue.output_token_limit == 1024
    assert life_query_result == dialogue
    dialogue_schema = candidate_schema(DIALOGUE_CANDIDATE_VERSION)
    model_output_schema = dialogue_model_output_schema(web_search=False)
    legacy_schema = candidate_schema()
    dialogue_schema_text = json.dumps(dialogue_schema, separators=(",", ":"))
    assert dialogue_schema != legacy_schema
    assert '"schema_version"' not in dialogue_schema_text
    assert '"reason_summary"' not in dialogue_schema_text
    assert '"decision"' not in dialogue_schema_text
    assert model_output_schema != dialogue_schema
    encoded_model_schema = json.dumps(model_output_schema, separators=(",", ":"))
    assert '"default"' not in encoded_model_schema
    assert '"discriminator"' not in encoded_model_schema
    assert len(encoded_model_schema) < len(dialogue_schema_text) * 3 // 4
    assert "title" not in model_output_schema["$defs"]["DialogueReplyDecision"]
    assert (
        "title"
        in model_output_schema["$defs"]["DialogueMaterialContentChange"]["properties"]
    )
    reply_schema = model_output_schema["$defs"]["DialogueReplyDecision"]
    mind_change_schema = model_output_schema["$defs"]["DialogueMindChange"]
    assert reply_schema["properties"]["mind_change"]["anyOf"][0] == {
        "$ref": "#/$defs/DialogueMindChange"
    }
    assert "current_mind_ref" not in mind_change_schema["properties"]
    assert mind_change_schema["properties"]["emotions"]["anyOf"][0] == {
        "$ref": "#/$defs/DialogueSummaryListReplacement"
    }
    assert DIALOGUE_MODEL_OUTPUT_VERSION == "armi.creator-dialogue-model-output.v1"
    assert "只用一句短句" in DIALOGUE_INSTRUCTIONS
    assert "四十个汉字" in DIALOGUE_INSTRUCTIONS
    assert "只回应一个重点" in DIALOGUE_INSTRUCTIONS
    assert "回应和追问通常二选一" in DIALOGUE_INSTRUCTIONS
    assert "最多问一个问题" in DIALOGUE_INSTRUCTIONS
    assert "不要复述已知情境" in DIALOGUE_INSTRUCTIONS
    assert "能直接说就直接说" in DIALOGUE_INSTRUCTIONS
    assert "普通闲聊优先用直白口语" in DIALOGUE_INSTRUCTIONS
    assert "不要主动拿光、风、窗等意象" in DIALOGUE_INSTRUCTIONS
    assert "不要声称自己看见、听见或触碰了现实环境" in DIALOGUE_INSTRUCTIONS
    assert "符合电子存在的真实处境" in DIALOGUE_INSTRUCTIONS

    request = json.loads(_request(dialogue).canonical_bytes)
    assert "candidate_base" not in request
    assert "included_context_refs" not in request
    assert "binding" not in request
    assert "context_digest" not in request
    assert "output_contract" not in request
    assert request["schema_version"] == "armi.creator-dialogue-input.v2"
    assert request["task"] == "respond_to_creator"
    assert request["available_refs"] == ["ctx:1"]
    assert [message["role"] for message in request["messages"]] == ["system", "user"]
    assert request["messages"][1]["content"] == "Hello"
    assert "# 本轮 Runtime Context" in request["messages"][0]["content"]
    assert "`ctx:1`" in request["messages"][0]["content"]
    assert "最后一条 `user` 消息对应 `ctx:1`" in request["messages"][0]["content"]
    assert str(_BUNDLE_ID) not in json.dumps(request)
    parsed = parse_candidate(
        json.dumps(_dialogue_candidate(), ensure_ascii=False).encode(),
        allowed_context_refs=frozenset(),
    )
    assert parsed.schema_version == DIALOGUE_CANDIDATE_VERSION
    assert parsed.model_dump(mode="json") == {
        "kind": "reply",
        "content": "Hello, I am here.",
        "experience": None,
        "memory_change": None,
        "relationship_change": None,
        "material_change": None,
        "capability_request": None,
        "self_change": None,
        "mind_change": None,
        "subject_prompt_change": None,
    }


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
    sections = []
    refs = []
    for ordinal, (section, kind, content, trust) in enumerate(items, 1):
        sections.append(
            {
                "section": section,
                "items": [
                    {
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
                ],
            }
        )
        refs.append({"ref": f"ctx:{ordinal}", "section": section, "item_kind": kind})
    compiled = json.dumps(
        {
            "schema_version": "armi.compiled-context.v1",
            "purpose": "consider_creator_input",
            "sections": sections,
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

    messages = request["messages"]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "我们曾经聊过雨声。" in messages[0]["content"]
    assert 'ref="ctx:2"' in messages[0]["content"]
    assert "uncertainty" not in messages[0]["content"]
    assert "links" not in messages[0]["content"]
    assert "runtime_identity" not in messages[0]["content"]
    assert "authorization status" not in messages[0]["content"]
    assert "remaining uses" not in messages[0]["content"]
    assert "实际发送权限由 Runtime 在模型外核对" in messages[0]["content"]
    assert "最后一条 `user` 消息对应 `ctx:8`" in messages[0]["content"]
    assert "这是缺少前置 Creator 原话的半轮回复。" not in json.dumps(
        messages, ensure_ascii=False
    )
    assert messages[1]["content"] == "窗外的光很好看。"
    assert messages[2]["content"] == "我也想知道那片光落在哪里。"
    assert messages[3]["content"] == "你想聊些什么?"
    assert request["available_refs"] == ["ctx:2", "ctx:7", "ctx:8"]
    assert source_id not in json.dumps(request, ensure_ascii=False)

    assert (
        _provider_input(
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
        == messages
    )


def test_creator_outreach_has_a_narrow_compact_purpose_profile() -> None:
    outreach = load_purpose_binding("consider_creator_outreach")
    assert outreach.profile == "creator_outreach"
    assert outreach.response_contract_version == DIALOGUE_CANDIDATE_VERSION
    assert outreach.output_token_limit == 512


def test_creator_dialogue_growth_contract_requires_same_turn_experience() -> None:
    value = {
        "kind": "reply",
        "content": "我想把这个变化认真留下来。",
        "experience": {"first_person_gist": "我在这次交流里作出了自己的选择。"},
        "self_change": {
            "name": {"value": "阿米"},
            "interests": {"values": ["持续理解自己的生活"]},
        },
        "mind_change": {
            "understanding": {"values": ["这次选择来自我现在的真实处境"]},
            "emotions": {"values": ["认真而期待"]},
            "mood": {"value": "期待"},
        },
    }
    parsed = parse_candidate(
        json.dumps(value, ensure_ascii=False).encode(),
        allowed_context_refs=frozenset(),
    )
    assert parsed.schema_version == DIALOGUE_CANDIDATE_VERSION
    dumped = parsed.model_dump(mode="json")
    assert dumped["self_change"]["name"] == {"value": "阿米"}
    assert dumped["self_change"]["interests"] == {"values": ["持续理解自己的生活"]}
    assert dumped["mind_change"]["mood"] == {"value": "期待"}

    without_experience = dict(value)
    without_experience.pop("experience")
    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            json.dumps(without_experience, ensure_ascii=False).encode(),
            allowed_context_refs=frozenset(),
        )

    historical = parse_candidate(
        b'{"kind":"reply","content":"historical"}',
        allowed_context_refs=frozenset(),
        expected_version="armi.creator-dialogue-candidate.v11",
    )
    assert historical.schema_version == "armi.creator-dialogue-candidate.v11"
    assert "self_change" not in historical.model_dump(mode="json")


def test_creator_dialogue_capability_request_is_context_bound() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我想申请使用受限执行能力。",
                "capability_request": {"capability_ref": "ctx:6"},
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset({"ctx:6"}),
    )
    assert parsed.model_dump(mode="json")["capability_request"] == {
        "capability_ref": "ctx:6"
    }

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-REFERENCE"):
        parse_candidate(
            json.dumps(
                {
                    "kind": "reply",
                    "content": "这条申请引用了不存在的能力。",
                    "capability_request": {"capability_ref": "ctx:7"},
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset({"ctx:6"}),
        )

    historical = parse_candidate(
        b'{"schema_version":"armi.creator-dialogue-candidate.v9",'
        b'"kind":"reply","content":"historical"}',
        allowed_context_refs=frozenset(),
    )
    assert historical.schema_version == "armi.creator-dialogue-candidate.v9"
    assert "capability_request" not in historical.model_dump(mode="json")

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            json.dumps(
                {
                    "kind": "reply",
                    "content": "聊天内容不能直接授予能力。",
                    "capability_request": {
                        "capability_ref": "ctx:6",
                        "authorization_status": "granted",
                    },
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset({"ctx:6"}),
        )


def test_creator_dialogue_material_contract_is_runtime_owned_and_context_bound() -> (
    None
):
    created = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我把它写成了一篇日记。",
                "material_change": {
                    "action": "create",
                    "material_kind": "diary",
                    "title": "今天",
                    "body": "我今天第一次认真记录这件事。",
                    "metadata": {"mood": "calm"},
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
    )
    assert created.schema_version == DIALOGUE_CANDIDATE_VERSION
    assert created.model_dump(mode="json")["material_change"]["action"] == "create"

    updated = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我更新了这篇日记。",
                "material_change": {
                    "action": "update",
                    "material_ref": "ctx:4",
                    "title": "今天-补记",
                    "body": "这是完整替换后的正文。",
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset({"ctx:4"}),
    )
    assert updated.model_dump(mode="json")["material_change"]["material_ref"] == (
        "ctx:4"
    )

    for action in ("set_private", "set_creator_visible", "delete"):
        state_change = parse_candidate(
            json.dumps(
                {
                    "kind": "reply",
                    "content": "这是我对自己资料作出的决定。",
                    "material_change": {
                        "action": action,
                        "material_ref": "ctx:4",
                    },
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset({"ctx:4"}),
        )
        assert (
            state_change.model_dump(mode="json")["material_change"]["action"] == action
        )

    for invalid in (
        {
            "kind": "reply",
            "content": "越权",
            "material_change": {
                "action": "create",
                "material_kind": "diary",
                "title": "标题",
                "body": "正文",
                "owner_party_id": str(uuid7()),
            },
        },
        {
            "kind": "reply",
            "content": "越权",
            "material_change": {
                "action": "update",
                "material_ref": "ctx:4",
                "material_kind": "diary",
                "title": "标题",
                "body": "正文",
            },
        },
        {
            "kind": "reply",
            "content": "无效内容",
            "material_change": {
                "action": "create",
                "material_kind": "diary",
                "title": "标题",
                "body": "正文",
                "metadata": {"note": "含有\u0000空字符"},
            },
        },
        {
            "kind": "reply",
            "content": "越权公开",
            "material_change": {
                "action": "publish",
                "material_ref": "ctx:4",
            },
        },
        {
            "kind": "reply",
            "content": "越权共享",
            "material_change": {
                "action": "set_private",
                "material_ref": "ctx:4",
                "privacy_status": "shared",
            },
        },
    ):
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(invalid, ensure_ascii=False).encode(),
                allowed_context_refs=frozenset({"ctx:4"}),
            )


def test_creator_dialogue_memory_is_optional_and_cannot_claim_authority() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我记住了。",
                "experience": {
                    "first_person_gist": "创造者告诉了我一个偏好。",
                    "uncertainty": "这仍是创造者的陈述。",
                    "memory_summary": "创造者向我表达过这个偏好。",
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
    )
    assert parsed.model_dump(mode="json")["experience"] == {
        "first_person_gist": "创造者告诉了我一个偏好。",
        "uncertainty": "这仍是创造者的陈述。",
        "memory_summary": "创造者向我表达过这个偏好。",
    }

    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(
                {
                    "kind": "reply",
                    "content": "越权",
                    "experience": {
                        "first_person_gist": "内容",
                        "memory_summary": "摘要",
                        "source_kind": "experienced",
                    },
                },
                ensure_ascii=False,
            ).encode(),
            allowed_context_refs=frozenset(),
        )


def test_creator_dialogue_memory_revision_is_narrow_and_strict() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我现在有了不同的理解。",
                "memory_change": {
                    "action": "reinterpret",
                    "memory_ref": "ctx:4",
                    "summary": "我现在把那次表达理解为一种仍可讨论的偏好。",
                    "uncertainty": "这只是我当前的理解。",
                    "related_memory_ref": "ctx:5",
                    "relation_kind": "contradicts",
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset({"ctx:4", "ctx:5"}),
    )
    assert parsed.model_dump(mode="json")["memory_change"]["action"] == ("reinterpret")

    for invalid in (
        {
            "action": "forget",
            "memory_ref": "ctx:4",
            "summary": "模型不得为遗忘改写摘要。",
        },
        {
            "action": "reinterpret",
            "memory_ref": "ctx:4",
            "summary": "越权",
            "memory_id": "019f0000-0000-7000-8000-000000000001",
        },
        {
            "action": "reinterpret",
            "memory_ref": "ctx:4",
            "summary": "关系不完整",
            "related_memory_ref": "ctx:5",
        },
    ):
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(
                    {
                        "kind": "reply",
                        "content": "无效",
                        "memory_change": invalid,
                    },
                    ensure_ascii=False,
                ).encode(),
                allowed_context_refs=frozenset({"ctx:4", "ctx:5"}),
            )


def test_creator_dialogue_relationship_change_is_narrow_and_experience_bound() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我会尊重这个边界。",
                "experience": {"first_person_gist": "创造者明确要求我停止联系。"},
                "relationship_change": {
                    "interpretation": "我理解这段接触现在应当结束。",
                    "fact": {
                        "kind": "party_expression",
                        "summary": "创造者表达了结束接触的决定。",
                    },
                    "boundary": {
                        "party": "creator",
                        "kind": "exit",
                        "action": "end_contact",
                        "summary": "创造者要求结束接触。",
                    },
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
    )
    change = parsed.model_dump(mode="json")["relationship_change"]
    assert change["boundary"]["action"] == "end_contact"

    for invalid in (
        {
            "kind": "reply",
            "content": "没有经历来源",
            "relationship_change": {"interpretation": "不能提交"},
        },
        {
            "kind": "reply",
            "content": "错误边界",
            "experience": {"first_person_gist": "一次交流。"},
            "relationship_change": {
                "boundary": {
                    "party": "armi",
                    "kind": "contact",
                    "action": "end_contact",
                    "summary": "错误形状",
                }
            },
        },
        {
            "kind": "reply",
            "content": "伪造共同经历",
            "experience": {"first_person_gist": "本轮真实交流。"},
            "relationship_change": {
                "interpretation": "不能由模型另造共同经历。",
                "fact": {
                    "kind": "shared_experience",
                    "summary": "并未发生的共同历史。",
                },
            },
        },
    ):
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(invalid, ensure_ascii=False).encode(),
                allowed_context_refs=frozenset(),
            )


def test_creator_dialogue_commitment_change_is_narrow_and_context_bound() -> None:
    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "reply",
                "content": "我答应联系前先问你是否方便。",
                "experience": {"first_person_gist": "我作出了一个明确承担。"},
                "relationship_change": {
                    "interpretation": "我愿意尊重创造者当时的状态。",
                    "commitment_change": {
                        "action": "establish",
                        "party": "armi",
                        "scope": "主动联系",
                        "content": "联系前先询问是否方便。",
                        "event_summary": "我明确作出了联系前先询问的承诺。",
                    },
                },
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
    )
    commitment = parsed.model_dump(mode="json")["relationship_change"][
        "commitment_change"
    ]
    assert commitment["party"] == "armi"
    assert commitment["commitment_ref"] is None

    invalid_changes = (
        {
            "action": "fulfill",
            "event_summary": "没有引用当前承诺。",
        },
        {
            "action": "establish",
            "party": "armi",
            "scope": "联系",
            "content": "先询问。",
            "event_summary": "试图携带 Runtime 身份。",
            "commitment_id": "01985d00-0000-7000-8000-000000000001",
        },
        {
            "action": "note_conflict",
            "commitment_ref": "ctx:7",
            "conflicts_with_ref": "ctx:7",
            "event_summary": "承诺不能与自己冲突。",
        },
        {
            "action": "withdraw",
            "commitment_ref": "ctx:9",
            "event_summary": "引用未提供的承诺。",
        },
    )
    for commitment_change in invalid_changes:
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(
                    {
                        "kind": "reply",
                        "content": "无效承诺变化。",
                        "experience": {"first_person_gist": "一次交流。"},
                        "relationship_change": {"commitment_change": commitment_change},
                    },
                    ensure_ascii=False,
                ).encode(),
                allowed_context_refs=frozenset({"ctx:7"}),
            )


def test_web_dialogue_v6_is_compact_versioned_and_rejects_urls() -> None:
    schema = candidate_schema(WEB_DIALOGUE_CANDIDATE_VERSION)
    schema_text = json.dumps(schema, separators=(",", ":"))
    assert '"web_research"' in schema_text
    assert '"schema_version"' not in schema_text
    assert '"subject_id"' not in schema_text

    parsed = parse_candidate(
        json.dumps(
            {"kind": "web_research", "query": "PostgreSQL 18 正式发布说明"},
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
        expected_version=WEB_DIALOGUE_CANDIDATE_VERSION,
    )
    assert parsed.schema_version == WEB_DIALOGUE_CANDIDATE_VERSION
    assert parsed.model_dump(mode="json") == {
        "kind": "web_research",
        "query": "PostgreSQL 18 正式发布说明",
    }

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-LIMIT"):
        parse_candidate(
            b'{"kind":"web_research","query":"https://example.com/"}',
            allowed_context_refs=frozenset(),
            expected_version=WEB_DIALOGUE_CANDIDATE_VERSION,
        )


def test_dialogue_exact_life_query_schema_excludes_logs_and_admin_data() -> None:
    schema_text = json.dumps(candidate_schema(DIALOGUE_CANDIDATE_VERSION))
    assert '"exact_life_query"' in schema_text
    assert '"self_change"' in schema_text
    assert '"audit"' not in schema_text
    assert '"credential"' not in schema_text

    parsed = parse_candidate(
        json.dumps(
            {
                "kind": "exact_life_query",
                "record_kind": "material",
                "query_text": "我的私人草稿",
            },
            ensure_ascii=False,
        ).encode(),
        allowed_context_refs=frozenset(),
        expected_version=DIALOGUE_CANDIDATE_VERSION,
    )
    assert parsed.schema_version == DIALOGUE_CANDIDATE_VERSION
    assert parsed.model_dump(mode="json") == {
        "kind": "exact_life_query",
        "record_kind": "material",
        "query_text": "我的私人草稿",
    }

    with pytest.raises(ModelViolation, match="MODEL-RESPONSE-SCHEMA"):
        parse_candidate(
            b'{"kind":"exact_life_query","record_kind":"audit","query_text":"logs"}',
            allowed_context_refs=frozenset(),
            expected_version=DIALOGUE_CANDIDATE_VERSION,
        )


def test_manifest_rejects_a_second_binding_or_fixed_model(tmp_path: Path) -> None:
    manifest = json.loads(
        Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/"
            "model-bindings.manifest.json"
        ).read_text(encoding="utf-8")
    )
    manifest["bindings"].append(dict(manifest["bindings"][0]))
    path = tmp_path / "model-bindings.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)


def test_web_dialogue_manifest_requires_explicit_v2_expectation(tmp_path: Path) -> None:
    manifest = json.loads(
        Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/"
            "model-bindings.manifest.json"
        ).read_text(encoding="utf-8")
    )
    manifest["purpose_profiles"]["consider_creator_input"][
        "response_contract_version"
    ] = WEB_DIALOGUE_CANDIDATE_VERSION
    manifest["purpose_profiles"]["consider_life_query_result"][
        "response_contract_version"
    ] = WEB_DIALOGUE_CANDIDATE_VERSION
    path = tmp_path / "model-bindings.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_binding(path)
    binding = load_purpose_binding(
        "consider_creator_input",
        path,
        expected_dialogue_version=WEB_DIALOGUE_CANDIDATE_VERSION,
    )
    assert binding.response_contract_version == WEB_DIALOGUE_CANDIDATE_VERSION
    request = json.loads(_request(binding).canonical_bytes)
    assert "candidate_base" not in request
    assert request["schema_version"] == "armi.creator-dialogue-input.v2"
    assert "output_contract" not in request

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

    assert isinstance(parsed, CognitionCandidateV7)
    assert parsed.experiences[0].payload.uncertainty is None


class _Transport(ArkTransport):
    def __init__(
        self,
        *,
        provider_model_id: str,
        candidate: dict[str, object] | None = None,
    ) -> None:
        self.provider_model_id = provider_model_id
        self.candidate = candidate or _candidate()
        self.keys_seen: list[bytes] = []

    async def tokenize(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request_bytes: bytes,
    ) -> int:
        del binding, request_bytes
        self.keys_seen.append(bytes(api_key))
        return 128

    async def invoke(
        self,
        *,
        api_key: memoryview,
        binding: ModelBinding,
        request,
    ) -> dict[str, object]:
        del binding, request
        self.keys_seen.append(bytes(api_key))
        candidate = json.dumps(self.candidate, ensure_ascii=False)
        return {
            "provider_request_id": "req-safe-id",
            "model_id": self.provider_model_id,
            "output_text": candidate,
            "usage": {
                "input_tokens": 128,
                "output_tokens": 64,
                "cached_input_tokens": 0,
            },
            "raw": {
                "output": [{"type": "message"}],
            },
        }


@pytest.mark.asyncio
async def test_adapter_records_provider_resolved_model_identity_without_fallback() -> (
    None
):
    binding = load_active_binding()
    transport = _Transport(provider_model_id="doubao-seed-evolving-20260731")
    locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL_TEST")
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL_TEST": "test-" + "credential"},
            secret_roots=(Path.cwd(),),
        ),
        locator=locator,
        candidate_schema=candidate_schema(),
        candidate_parser=parse_candidate,
        transport=transport,
    )
    result = await adapter.invoke(_request(binding))
    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.provider_model_id == "doubao-seed-evolving-20260731"
    assert result.response_bytes is not None
    assert b"credential" not in result.response_bytes
    assert transport.keys_seen == [b"test-credential"]


@pytest.mark.asyncio
async def test_dialogue_artifact_keeps_call_metadata_outside_minimal_candidate() -> (
    None
):
    binding = load_purpose_binding("consider_creator_input")
    locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL_TEST")
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL_TEST": "test-credential"},
            secret_roots=(Path.cwd(),),
        ),
        locator=locator,
        candidate_schema=dialogue_model_output_schema(web_search=False),
        candidate_parser=parse_candidate,
        transport=_Transport(
            provider_model_id="doubao-seed-evolving-20260731",
            candidate={
                **_dialogue_candidate(),
                "memory_change": {"action": "recall", "memory_ref": "ctx:1"},
            },
        ),
    )

    result = await adapter.invoke(_request(binding))

    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.response_bytes is not None
    artifact = json.loads(result.response_bytes)
    assert artifact["candidate"] == {
        "kind": "reply",
        "content": "Hello, I am here.",
        "memory_change": {"action": "recall", "memory_ref": "ctx:1"},
    }
    assert artifact["provider_model_id"] == "doubao-seed-evolving-20260731"
    assert artifact["usage"] == {
        "input_tokens": 128,
        "output_tokens": 64,
        "cached_input_tokens": 0,
    }


@pytest.mark.asyncio
async def test_adapter_preserves_invalid_runtime_reference_failure() -> None:
    binding = load_purpose_binding("consider_creator_input")
    locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL_TEST")
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL_TEST": "test-credential"},
            secret_roots=(Path.cwd(),),
        ),
        locator=locator,
        candidate_schema=dialogue_model_output_schema(web_search=False),
        candidate_parser=parse_candidate,
        transport=_Transport(
            provider_model_id="doubao-seed-evolving-20260731",
            candidate={
                **_dialogue_candidate(),
                "memory_change": {"action": "recall", "memory_ref": "ctx:7"},
            },
        ),
    )

    result = await adapter.invoke(_request(binding))

    assert result.status is ModelResultStatus.REJECTED
    assert result.error_code == "MODEL-RESPONSE-REFERENCE"


@pytest.mark.asyncio
async def test_adapter_rejects_non_seed_provider_identity() -> None:
    binding = load_active_binding()
    locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL_TEST")
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL_TEST": "test-" + "credential"},
            secret_roots=(Path.cwd(),),
        ),
        locator=locator,
        candidate_schema=candidate_schema(),
        candidate_parser=parse_candidate,
        transport=_Transport(provider_model_id="foreign-model"),
    )
    with pytest.raises(ModelViolation, match="MODEL-PROVIDER-RESPONSE"):
        await adapter.invoke(_request(binding))


@pytest.mark.asyncio
async def test_active_adapter_rejects_historical_candidate_contract() -> None:
    binding = load_active_binding()
    historical = _candidate()
    historical["schema_version"] = "armi.cognition-candidate.v3"
    historical["action_intents"] = historical.pop("action_choices")
    locator = CredentialLocator.parse("env:ARMI_SECRET_MODEL_TEST")
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={"ARMI_SECRET_MODEL_TEST": "test-" + "credential"},
            secret_roots=(Path.cwd(),),
        ),
        locator=locator,
        candidate_schema=candidate_schema(),
        candidate_parser=parse_candidate,
        transport=_Transport(
            provider_model_id="doubao-seed-evolving-20260731",
            candidate=historical,
        ),
    )
    result = await adapter.invoke(_request(binding))
    assert result.status is ModelResultStatus.REJECTED
    assert result.error_code == "MODEL-RESPONSE-SCHEMA"
    assert result.provider_request_id == "req-safe-id"
    assert result.provider_model_id == "doubao-seed-evolving-20260731"
    assert result.usage is not None
    assert result.usage.input_tokens == 128
    assert result.usage.output_tokens == 64
