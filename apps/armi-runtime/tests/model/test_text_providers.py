"""Real SDK serialization against isolated HTTP transports; no provider calls."""

# ruff: noqa: RUF001 -- Match the Chinese instruction delimiters exactly.

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
from armi_cognition.api import CognitionSchemaDocument
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    CandidateViolation,
    CredentialLocator,
    ModelRequest,
    ModelViolation,
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_kernel.contracts import Digest
from armi_local_control.configuration import EnvironmentFileCredentialPort
from armi_runtime.adapters.model.compatible import CompatibleStructuredTransport
from armi_runtime.adapters.model.model_clients import ModelClients
from armi_runtime.composition.credential_scope import ScopedCredentialPort
from armi_runtime.composition.model_adapter import create_model_adapter
from armi_runtime.composition.model_verification import (
    load_active_binding as load_active_model_binding,
)
from armi_runtime.composition.model_verification import load_voice_model_binding
from jsonschema import Draft202012Validator
from openai import AsyncOpenAI

pytestmark = pytest.mark.test_group("model", "cognition")


def binding(provider):
    current = load_active_model_binding()
    return (
        current
        if provider == "qwen"
        else replace(
            current,
            provider="deepseek",
            model_id="deepseek-flash",
            api_base="https://api.deepseek.com",
            credential_identity="armi.model.deepseek-api-key.v1",
        )
    )


def request():
    document = {
        "schema_version": "armi.model-request.v1",
        "compiled_context": {
            "purpose": "consider_other_human_input",
            "layers": [
                {"items": [{"item_kind": "current_evidence", "content": "在吗"}]}
            ],
        },
        "included_context_refs": [{"ref": "ctx:1"}],
    }
    data = json.dumps(document, ensure_ascii=False).encode()
    return ModelRequest(data, Digest.from_bytes(data), 10, 2048)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
@pytest.mark.parametrize("finish", ["completed", "incomplete"])
async def test_sdk_wire_usage_and_failure_preserve_single_responses_call(
    monkeypatch, provider, finish
):
    requests, receipts = [], []
    selected = binding(provider)
    output = '{"candidate":{"reply":"在呢"}}'

    def respond(req):
        requests.append(req)
        body = {
            "id": "resp-test",
            "object": "response",
            "created_at": 1,
            "model": selected.model_id,
            "status": finish,
            "output": [
                {
                    "type": "message",
                    "id": "msg",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": output, "annotations": []}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 17,
                "output_tokens": 9,
                "total_tokens": 26,
                "input_tokens_details": {"cached_tokens": 5},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        return httpx.Response(200, json=body)

    def make_client(**kwargs):
        assert kwargs["max_retries"] == 0
        kwargs["http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )
        return AsyncOpenAI(**kwargs)

    monkeypatch.setattr(
        "armi_runtime.adapters.model.model_clients.AsyncOpenAI", make_client
    )
    clients = ModelClients()
    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}},
        "required": ["reply"],
        "additionalProperties": False,
    }
    transport = CompatibleStructuredTransport(
        schema, instructions="保持原逻辑", schema_name="reply", clients=clients
    )
    adapter = create_model_adapter(
        binding=selected,
        credential_port=Mock(),
        locator=None,
        candidate_schema=CognitionSchemaDocument(json.dumps(schema).encode()),
        instructions="保持原逻辑",
        schema_name="reply",
        clients=clients,
    )

    async def save(receipt):
        receipts.append(receipt)

    try:
        count = await transport.tokenize(
            api_key=memoryview(b"isolated-key"),
            binding=selected,
            request_bytes=request().canonical_bytes,
        )
        assert count > len(request().canonical_bytes)
        assert requests == []
        with provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")):
            result = await transport.invoke(
                api_key=memoryview(b"isolated-key"), binding=selected, request=request()
            )
        assert len(requests) == 1
        wire = json.loads(requests[0].content)
        assert (
            wire == json.loads(adapter.request_evidence(request()))["provider_request"]
        )
        assert requests[0].headers["authorization"] == "Bearer isolated-key"
        assert requests[0].url.path.endswith("/responses")
        assert wire["reasoning"] == {"effort": "none"}
        assert "response_format" not in wire and "enable_thinking" not in wire
        assert "保持原逻辑" in wire["instructions"]
        assert (
            json.dumps(
                transport.output_format(request())["schema"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            in wire["instructions"]
        )
        if provider == "qwen":
            assert "text" not in wire
            assert wire["temperature"] == 1.0
            assert "top_p" not in wire
            assert wire["store"] is False
        else:
            assert requests[0].url.path == "/responses"
            assert wire["text"] == {"format": {"type": "json_object"}}
            assert wire["temperature"] == 1.0
            assert wire["top_p"] == 1.0
            assert "thinking" not in wire and "store" not in wire
        settled = adapter._settle_response(result, request())
        assert settled.response_bytes is not None and settled.usage is not None
        assert json.loads(settled.response_bytes)["output_text"] == output
        assert (
            settled.usage.input_tokens == 17 and settled.usage.cached_input_tokens == 5
        )
        assert settled.response_error_code == (
            None if finish == "completed" else "MODEL-RESPONSE-INCOMPLETE"
        )
        assert receipts[-1].provider == provider
        assert {q.unit.value: q.quantity for q in receipts[-1].quantities}[
            "input_tokens"
        ] == 17
    finally:
        await clients.close()


def test_ark_is_rejected_for_primary_but_voice_is_unchanged(tmp_path):
    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    manifest["active_binding"] = "armi.model-adapter.volcengine-ark-responses-v1"
    manifest["bindings"][0].update(
        provider="volcengine_ark",
        model_id="doubao-seed-evolving",
        api_base="https://ark.cn-beijing.volces.com/api/v3",
    )
    path = tmp_path / "model-bindings.yaml"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelViolation, match="MODEL-BINDING-MANIFEST"):
        load_active_model_binding(path)
    voice = load_voice_model_binding()
    assert (
        voice.provider == "volcengine_ark"
        and voice.model_id == "doubao-seed-character-260628"
    )


@pytest.mark.parametrize(
    "provider,base",
    [
        ("qwen", "https://api.deepseek.com"),
        ("deepseek", "https://untrusted.example"),
        ("qwen", "https://dashscope.aliyuncs.com.evil/compatible-mode/v1"),
    ],
)
def test_provider_key_cannot_be_redirected_to_other_host(provider, base):
    with pytest.raises(ModelViolation, match="MODEL-BINDING-API-BASE"):
        replace(binding(provider), api_base=base)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
@pytest.mark.parametrize(
    "http_status,code",
    [
        (401, "MODEL-CREDENTIAL"),
        (429, "MODEL-RATE-LIMITED"),
        (500, "MODEL-PROVIDER-UNAVAILABLE"),
    ],
)
async def test_provider_uses_only_its_key_and_does_not_retry_or_fallback(
    tmp_path, monkeypatch, provider, http_status, code
):
    secret = tmp_path / "key"
    secret.write_bytes(b"isolated-text-key")
    locator = CredentialLocator.parse("file:" + secret.as_posix())
    credentials = ScopedCredentialPort(
        EnvironmentFileCredentialPort(environment={}, secret_roots=(tmp_path,)),
        allowed={f"model.request.{provider}": locator},
    )
    calls = []
    receipts = []

    def respond(req):
        calls.append(req)
        return httpx.Response(
            http_status, json={"error": {"message": "isolated failure"}}
        )

    def make_client(**kwargs):
        kwargs["http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )
        return AsyncOpenAI(**kwargs)

    monkeypatch.setattr(
        "armi_runtime.adapters.model.model_clients.AsyncOpenAI", make_client
    )
    adapter = create_model_adapter(
        binding=binding(provider),
        credential_port=credentials,
        locator=locator,
        candidate_schema=CognitionSchemaDocument(b'{"type":"object"}'),
        instructions="test",
        schema_name="test",
    )

    async def save(receipt):
        receipts.append(receipt)

    try:
        with (
            provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")),
            pytest.raises(ModelViolation, match=code),
        ):
            await adapter.invoke(request())
        assert len(calls) == 1
        assert calls[0].headers["authorization"] == "Bearer isolated-text-key"
        assert receipts[-1].provider == provider
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "provider,model",
    [
        ("qwen", "qwen3.7-plus"),
        ("deepseek", "deepseek-flash"),
        ("deepseek", "deepseek-v4-pro"),
    ],
)
def test_switching_binding_preserves_purpose_contract_and_voice(
    tmp_path, provider, model
):
    from armi_runtime.composition.model_verification import load_purpose_binding

    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    row = manifest["bindings"][0]
    row.update(
        provider=provider,
        model_id=model,
        api_base="https://api.deepseek.com"
        if provider == "deepseek"
        else "https://dashscope.aliyuncs.com/compatible-mode/v1",
        credential_identity=f"armi.model.{provider}-api-key.v1",
        credential_locator=f"model.{provider}_api_key",
        credential_purpose=f"model.request.{provider}",
    )
    manifest["active_binding"] = f"armi.model-adapter.{provider}-responses-v1"
    path = tmp_path / "bindings.yaml"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert load_active_model_binding(path).model_id == model
    for purpose in manifest["purpose_profiles"]:
        current = load_purpose_binding(purpose, path)
        original = load_purpose_binding(purpose)
        assert current.profile == original.profile
        assert current.response_contract_version == original.response_contract_version
        assert current.output_token_limit == original.output_token_limit
    assert load_voice_model_binding(path) == load_voice_model_binding()


def test_every_purpose_renders_the_same_backend_schema_for_both_providers():
    from armi_runtime.composition.model_verification import (
        candidate_schema,
        load_purpose_binding,
    )

    manifest = cast(dict[str, Any], load_yaml_file(Path("configs/model-bindings.yaml")))
    for purpose in manifest["purpose_profiles"]:
        selected = load_purpose_binding(purpose)
        schema = candidate_schema(selected.response_contract_version, purpose=purpose)
        renderer = CompatibleStructuredTransport(
            schema, instructions="business instructions", schema_name="test"
        )
        expected = renderer.output_format(request())["schema"]
        for provider in ("qwen", "deepseek"):
            wire = renderer.request_parameters(
                replace(binding(provider), profile=selected.profile), request()
            )
            rendered = (
                wire["instructions"]
                .split("完整 JSON Schema，必须满足全部字段、类型和约束：\n", 1)[1]
                .split("\n\n合法 JSON 格式示例", 1)[0]
                .split("\n\n完整对话 JSON 层级示例", 1)[0]
            )
            assert json.loads(rendered) == expected
            if "完整对话 JSON 层级示例" in wire["instructions"]:
                example_text = (
                    wire["instructions"]
                    .split(
                        "完整对话 JSON 层级示例（只示意格式，不代表本轮应作出的判断）：\n",
                        1,
                    )[1]
                    .split("\n注意 candidate.appraisal", 1)[0]
                )
                example = json.loads(example_text)
                Draft202012Validator(expected).validate(example)
                assert "appraisal" in example["candidate"]["appraisal"]
        if purpose == "consider_other_human_input":
            example_text = (
                wire["instructions"]
                .split("合法 JSON 格式示例（仅示意层级，实际内容按本轮判断）：\n", 1)[1]
                .split("\n注意", 1)[0]
            )
            Draft202012Validator(expected).validate(json.loads(example_text))
            experience_text = (
                wire["instructions"]
                .split("仅形成经历、没有关系变化的合法示例：\n", 1)[1]
                .split("\nrelationship_change", 1)[0]
            )
            value = json.loads(experience_text)
            Draft202012Validator(expected).validate(value)
            value["candidate"]["social"]["relationship_change"] = dict.fromkeys(
                ("interpretation", "fact", "boundary", "commitment_change")
            )
            assert not Draft202012Validator(expected).is_valid(value)


@pytest.mark.parametrize(
    "purpose", ["consider_creator_input", "consider_other_human_input"]
)
@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
def test_dialogue_example_covers_nested_appraisal_with_bound_refs(
    purpose,
    provider,
):
    from armi_runtime.composition.model_verification import (
        candidate_schema,
        load_purpose_binding,
    )

    selected = load_purpose_binding(purpose)
    schema = candidate_schema(selected.response_contract_version, purpose=purpose)
    renderer = CompatibleStructuredTransport(
        schema, instructions="", schema_name="test"
    )
    data = json.loads(request().canonical_bytes)
    data["included_context_refs"] = [{"ref": "ctx:7"}]
    payload = json.dumps(data).encode()
    current = ModelRequest(payload, Digest.from_bytes(payload), 10, 2048)
    wire = renderer.request_parameters(binding(provider), current)
    value = json.loads(
        wire["instructions"]
        .split("完整对话 JSON 层级示例（只示意格式，不代表本轮应作出的判断）：\n", 1)[1]
        .split("\n注意 candidate.appraisal", 1)[0]
    )
    expected = renderer.output_format(current)["schema"]
    Draft202012Validator(expected).validate(value)
    event = value["candidate"]["appraisal"]
    assert event["basis_refs"] == ["ctx:7"]
    assert set(event) == {
        "appraisal",
        "gist",
        "basis_refs",
        "trajectory",
        "event_phase",
    }
    # Preserve the event's valid refs, but reject a second copy on candidate.
    value["candidate"]["basis_refs"] = event["basis_refs"]
    errors = list(Draft202012Validator(expected).iter_errors(value))
    assert any(
        e.validator == "additionalProperties" and list(e.absolute_path) == ["candidate"]
        for e in errors
    )
    del value["candidate"]["basis_refs"]
    allowed_fields = (
        wire["instructions"]
        .split("candidate 的直接字段只能是：", 1)[1]
        .split("。", 1)[0]
        .split("、")
    )
    assert set(allowed_fields) == set(schema["properties"])
    assert "不得在 candidate 下再复制一份 basis_refs" in wire["instructions"]
    # The observed failure lost this event envelope; backend must still reject it.
    value["candidate"]["appraisal"] = event["appraisal"]
    assert not Draft202012Validator(expected).is_valid(value)
    assert "每层 2 空格缩进" in wire["instructions"]


@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
def test_relationship_generation_requires_interpretation_without_relaxing_backend(
    provider,
):
    from armi_runtime.composition.model_verification import (
        candidate_schema,
        load_purpose_binding,
        parse_candidate,
    )

    selected = load_purpose_binding("consider_other_human_input")
    schema = candidate_schema(selected.response_contract_version)
    renderer = CompatibleStructuredTransport(
        schema, instructions="", schema_name="test"
    )
    wire = renderer.request_parameters(binding(provider), request())
    output_schema = renderer.output_format(request())["schema"]
    value = {
        "candidate": {
            "decision": {"kind": "reply", "content": "在呢"},
            "appraisal": None,
            "social": {
                "experience": {
                    "first_person_gist": "我们聊到了各自的想法",
                    "uncertainty": None,
                },
                "relationship_change": {
                    "interpretation": None,
                    "fact": {"kind": "party_expression", "summary": "对方希望直接交流"},
                    "boundary": None,
                    "commitment_change": None,
                },
            },
        },
    }
    # This old branch is legal for an existing relationship, but not a new one.
    # The common backend stays unchanged; generation now selects a safe subset.
    parse_candidate(
        json.dumps(value["candidate"]).encode(),
        expected_version=selected.response_contract_version,
        allowed_context_refs=frozenset(),
    )
    assert not Draft202012Validator(output_schema).is_valid(value)
    value["candidate"]["social"]["relationship_change"]["interpretation"] = (
        "我们愿意直接交流"
    )
    Draft202012Validator(output_schema).validate(value)
    parse_candidate(
        json.dumps(value["candidate"]).encode(),
        expected_version=selected.response_contract_version,
        allowed_context_refs=frozenset(),
    )
    assert "interpretation" in wire["instructions"]
    # A live model added formatting commentary inside decision; do not strip it.
    value["candidate"]["decision"]["_note"] = "format checked"
    assert not Draft202012Validator(output_schema).is_valid(value)
    with pytest.raises(ModelViolation):
        parse_candidate(
            json.dumps(value["candidate"]).encode(),
            expected_version=selected.response_contract_version,
            allowed_context_refs=frozenset(),
        )


@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
@pytest.mark.parametrize(
    "output",
    [
        '{"candidate":{"decision":{"kind":"reply","content":"hello"},"appraisal":null,"social":null}}}',
        '{"candidate":{},"decision":{"kind":"reply","content":"hello"}}',
        '```json\n{"candidate":{}}\n```',
    ],
)
def test_shared_backend_rejects_malformed_envelopes_without_repair(provider, output):
    from armi_runtime.composition.model_verification import model_response_candidate

    adapter = create_model_adapter(
        binding=binding(provider),
        credential_port=Mock(),
        locator=None,
        candidate_schema=CognitionSchemaDocument(b'{"type":"object"}'),
        instructions="",
        schema_name="test",
        transport=Mock(),
    )
    result = adapter._settle_response(
        {
            "provider_request_id": "test",
            "model_id": binding(provider).model_id,
            "output_text": output,
            "usage": {"input_tokens": 1, "output_tokens": 1, "cached_input_tokens": 0},
            "raw": {"status": "completed", "output": [{"type": "message"}]},
        },
        request(),
    )
    assert result.response_bytes is not None
    assert json.loads(result.response_bytes)["output_text"] == output
    with pytest.raises(CandidateViolation, match="CANDIDATE-CONTRACT"):
        model_response_candidate(result.response_bytes)
