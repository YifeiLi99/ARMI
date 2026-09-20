"""Real SDK serialization against isolated HTTP transports; no provider calls."""

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
from openai import AsyncOpenAI


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
async def test_sdk_wire_usage_and_failure_preserve_single_strict_call(
    monkeypatch, provider, finish
):
    requests, receipts = [], []
    selected = binding(provider)
    output = '{"candidate":{"reply":"在呢"}}'

    def respond(req):
        requests.append(req)
        if provider == "qwen":
            body = {
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": selected.model_id,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop" if finish == "completed" else "length",
                        "message": {"role": "assistant", "content": output},
                    }
                ],
                "usage": {
                    "prompt_tokens": 17,
                    "completion_tokens": 9,
                    "total_tokens": 26,
                    "prompt_tokens_details": {"cached_tokens": 5},
                },
            }
        else:
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
        if provider == "qwen":
            assert requests[0].url.path.endswith("/chat/completions")
            assert wire["response_format"]["json_schema"]["strict"] is True
            assert wire["enable_thinking"] is False
            assert "text" not in wire
        else:
            assert requests[0].url.path == "/responses"
            assert wire["text"]["format"]["strict"] is True
            assert wire["reasoning"] == {"effort": "none"}
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
    manifest["active_binding"] = (
        f"armi.model-adapter.{provider}-{'chat' if provider == 'qwen' else 'responses'}-v1"
    )
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
