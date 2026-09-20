import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid7

import httpx
import pytest
from armi_cognition.api import CognitionSchemaDocument
from armi_runtime.composition import credential_probe as probe
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.model_adapter import create_model_adapter
from openai import AsyncOpenAI


def test_actual_voice_binding_initializes_responses_adapter():
    binding = probe.load_voice_model_binding(runtime_config_path("model-bindings.yaml"))
    adapter = create_model_adapter(
        binding=binding,
        credential_port=Mock(),
        locator=Mock(),
        candidate_schema=CognitionSchemaDocument(b'{"type":"object"}'),
        instructions="",
        schema_name="test",
        transport=Mock(),
    )
    assert adapter.binding == binding


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recognized,expected",
    [("你好这是语音连接测试", "passed"), ("", "failed"), ("别的内容", "failed")],
)
async def test_speech_probe_requires_real_audio_and_matching_recognition(
    monkeypatch, recognized, expected
):
    monkeypatch.setattr(
        probe,
        "load_effective_config",
        lambda **kw: SimpleNamespace(
            config=SimpleNamespace(
                voice=SimpleNamespace(
                    tts_resource_id="tts", tts_voice_type="voice", asr_resource_id="asr"
                )
            )
        ),
    )

    class Tts:
        def __init__(self, *args, **kwargs):
            pass

        async def synthesize(self, fragments):
            assert [text async for text in fragments] == [probe._PHRASE]
            yield b"audio"

        async def close(self):
            pass

    class Asr:
        def __init__(self, *args, **kwargs):
            pass

        async def recognize(self, frames):
            assert b"".join([frame async for frame in frames]) == b"audio"
            yield SimpleNamespace(text=recognized)

    monkeypatch.setattr(probe, "VolcStreamingTts", Tts)
    monkeypatch.setattr(probe, "VolcStreamingAsr", Asr)
    result = await probe.verify(
        "speech.volc_credentials", "test-key", Path("."), str(uuid7())
    )
    assert result["checks"]["tts"]["status"] == "passed"
    assert result["checks"]["asr"]["status"] == expected
    assert result["status"] == expected


@pytest.mark.asyncio
async def test_models_are_checked_separately_and_errors_are_redacted(monkeypatch):
    calls = []

    async def check(key, binding):
        calls.append(binding.model_id)
        if binding.profile == "creator_voice_act":
            raise ValueError("private-key-must-not-appear")
        return {"status": "passed"}

    monkeypatch.setattr(probe, "_model_check", check)
    result = await probe.verify(
        "model.ark_api_key", "test-key", Path("."), str(uuid7())
    )
    assert calls == ["doubao-seed-character-260628"]
    assert result["status"] == "failed"
    assert "model" not in result["checks"]
    assert "private-key" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("active", ["qwen", "deepseek"])
@pytest.mark.parametrize("provider", ["qwen", "deepseek"])
@pytest.mark.parametrize(
    "outcome", ["valid", "unauthorized", "invalid_output", "invalid_json"]
)
async def test_saved_key_verification_reaches_own_official_api(
    monkeypatch, tmp_path, active, provider, outcome
):
    binding = probe.load_active_model_binding()
    if active == "deepseek":
        binding = replace(
            binding,
            provider="deepseek",
            model_id="deepseek-v4-pro",
            api_base="https://api.deepseek.com",
            credential_identity="armi.model.deepseek-api-key.v1",
        )
    monkeypatch.setattr(probe, "load_active_model_binding", lambda path: binding)
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer isolated-test-key"
        if provider == "qwen":
            assert request.url.host == "dashscope.aliyuncs.com"
            assert request.url.path.endswith("/responses")
            assert body["reasoning"] == {"effort": "none"}
            assert "text" not in body and body["store"] is False
            assert "连接测试" in str(body["input"])
        else:
            assert request.url.host == "api.deepseek.com"
            assert request.url.path == "/responses"
            assert body["reasoning"] == {"effort": "none"}
            assert body["text"] == {"format": {"type": "json_object"}}
            assert body["model"] == (
                "deepseek-v4-pro" if active == provider else "deepseek-flash"
            )
        if outcome == "unauthorized":
            return httpx.Response(
                401,
                json={
                    "error": {
                        "message": "private-provider-message",
                        "type": "authentication_error",
                    }
                },
            )
        output = json.dumps({"candidate": {"ok": outcome == "valid"}})
        if outcome == "invalid_json":
            output = "not json"
        response = {
            "id": "resp-test",
            "object": "response",
            "created_at": 1,
            "model": body["model"],
            "status": "completed",
            "output": [
                {
                    "id": "msg",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": output, "annotations": []}
                    ],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        return httpx.Response(200, json=response)

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        kwargs["http_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        )
        return AsyncOpenAI(**kwargs)

    monkeypatch.setattr("armi_runtime.adapters.model.model_clients.AsyncOpenAI", client)
    result = await probe.verify(
        f"model.{provider}_api_key", "isolated-test-key", tmp_path, str(uuid7())
    )
    assert len(requests) == 1
    assert result["status"] == ("passed" if outcome == "valid" else "failed")
    assert "private-provider-message" not in str(result)
    assert "isolated-test-key" not in str(result)
    if outcome == "unauthorized":
        assert result["checks"]["model"]["error_code"] == "HTTP-401"
    elif outcome in {"invalid_output", "invalid_json"}:
        assert result["checks"]["model"]["error_code"] == "MODEL-PROVIDER-RESPONSE"


def test_local_context_failure_does_not_blame_key_or_network():
    result = probe._failure(probe.ModelViolation("MODEL-CONTEXT"))
    assert result["error_code"] == "MODEL-CONTEXT"
    assert "本地验证请求" in result["message"]
    assert "检查网络" not in result["message"]
