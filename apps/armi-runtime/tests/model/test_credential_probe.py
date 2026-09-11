from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from armi_cognition.api import CognitionSchemaDocument
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.composition import credential_probe as probe
from armi_runtime.composition.config_assets import runtime_config_path


def test_actual_voice_binding_initializes_responses_adapter():
    binding = probe.load_voice_model_binding(runtime_config_path("model-bindings.yaml"))
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=Mock(),
        locator=Mock(),
        candidate_schema=CognitionSchemaDocument(b'{"type":"object"}'),
        candidate_parser=Mock(),
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
    result = await probe.verify("speech.volc_credentials", "test-key", Path("."))
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
    result = await probe.verify("model.ark_api_key", "test-key", Path("."))
    assert len(calls) == 2
    assert result["status"] == "failed"
    assert result["checks"]["model"]["status"] == "passed"
    assert "private-key" not in str(result)
