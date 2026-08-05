"""ADP-MODEL and EVO-CONTRACT-MODEL offline contract checks."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid7

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
)
from armi_runtime.composition.configuration import EnvironmentFileCredentialPort
from armi_runtime.composition.model_contract import (
    ACTIVE_MODEL_ID,
    ACTIVE_VERSION_POLICY,
    ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    AUTONOMOUS_ACTIVITY_CANDIDATE_VERSION,
    DIALOGUE_CANDIDATE_VERSION,
    WEB_DIALOGUE_CANDIDATE_VERSION,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    load_purpose_binding,
    parse_candidate,
)

_BUNDLE_ID = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")


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
        b'{"kind":"progress","progress_summary":"done","next_step":"continue"}',
        allowed_context_refs=frozenset(),
        expected_version=ACTIVITY_ATTENTION_CANDIDATE_VERSION,
    )
    assert getattr(parsed, "kind", None) == "progress"
    schema_text = json.dumps(
        candidate_schema(ACTIVITY_ATTENTION_CANDIDATE_VERSION), separators=(",", ":")
    )
    assert "activity_id" not in schema_text
    assert '"failed"' not in schema_text

    invalid = (
        {"kind": "engage", "activity_id": str(uuid7())},
        {
            "kind": "wait",
            "progress_summary": "blocked",
            "next_step": "continue",
            "waiting_summary": "wait",
            "resumption_cue": "time",
            "condition_kind": "time",
        },
        {
            "kind": "wait",
            "progress_summary": "blocked",
            "next_step": "continue",
            "waiting_summary": "wait",
            "resumption_cue": "input",
            "condition_kind": "creator_input",
            "delay_seconds": 60,
        },
    )
    for value in invalid:
        with pytest.raises(ModelViolation):
            parse_candidate(
                json.dumps(value).encode(),
                allowed_context_refs=frozenset(),
                expected_version=ACTIVITY_ATTENTION_CANDIDATE_VERSION,
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
    context = b'{"schema_version":"armi.compiled-context.v1"}\n'
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


def test_only_evolving_binding_is_active_and_digest_is_stable() -> None:
    first = load_active_binding()
    second = load_active_binding()
    assert first.model_id == ACTIVE_MODEL_ID == "doubao-seed-evolving"
    assert first.version_policy == ACTIVE_VERSION_POLICY
    assert first.response_model_identity_required
    assert first.input_microyuan_per_million == 6_000_000
    assert first.output_microyuan_per_million == 30_000_000
    assert first.digest == second.digest
    assert _request(first).digest == _request(second).digest


def test_creator_dialogue_uses_compact_purpose_contract() -> None:
    legacy = load_active_binding()
    dialogue = load_purpose_binding("consider_creator_input")
    assert dialogue.model_id == legacy.model_id == ACTIVE_MODEL_ID
    assert dialogue.profile == "creator_dialogue"
    assert dialogue.response_contract_version == DIALOGUE_CANDIDATE_VERSION
    assert dialogue.output_token_limit == 1024
    dialogue_schema = candidate_schema(DIALOGUE_CANDIDATE_VERSION)
    legacy_schema = candidate_schema()
    dialogue_schema_text = json.dumps(dialogue_schema, separators=(",", ":"))
    assert len(json.dumps(dialogue_schema, separators=(",", ":"))) < 4_096
    assert len(json.dumps(dialogue_schema)) < len(json.dumps(legacy_schema)) // 4
    assert '"schema_version"' not in dialogue_schema_text
    assert '"reason_summary"' not in dialogue_schema_text
    assert '"decision"' not in dialogue_schema_text

    request = json.loads(_request(dialogue).canonical_bytes)
    assert "candidate_base" not in request
    assert "included_context_refs" not in request
    assert request["output_contract"]["schema_version"] == DIALOGUE_CANDIDATE_VERSION
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
    }


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


def test_web_dialogue_v4_is_compact_versioned_and_rejects_urls() -> None:
    schema = candidate_schema(WEB_DIALOGUE_CANDIDATE_VERSION)
    schema_text = json.dumps(schema, separators=(",", ":"))
    assert '"web_research"' in schema_text
    assert '"schema_version"' not in schema_text
    assert '"subject_id"' not in schema_text
    assert len(schema_text) < 6_144

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
    assert request["output_contract"]["schema_version"] == (
        WEB_DIALOGUE_CANDIDATE_VERSION
    )

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
        candidate_schema=candidate_schema(DIALOGUE_CANDIDATE_VERSION),
        candidate_parser=parse_candidate,
        transport=_Transport(
            provider_model_id="doubao-seed-evolving-20260731",
            candidate=_dialogue_candidate(),
        ),
    )

    result = await adapter.invoke(_request(binding))

    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.response_bytes is not None
    artifact = json.loads(result.response_bytes)
    assert artifact["candidate"] == {
        "kind": "reply",
        "content": "Hello, I am here.",
    }
    assert artifact["provider_model_id"] == "doubao-seed-evolving-20260731"
    assert artifact["usage"] == {
        "input_tokens": 128,
        "output_tokens": 64,
        "cached_input_tokens": 0,
    }


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
