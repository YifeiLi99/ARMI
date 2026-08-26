from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from armi_live_voice.api import LiveVoiceViolation
from armi_runtime.adapters.voice.ark import ArkResponsesFastModel


class FakeResponses:
    def __init__(self, output_text: str = '{"ok":true}') -> None:
        self.output_text = output_text
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object):
        self.requests.append(request)
        return SimpleNamespace(output_text=self.output_text)


def _adapter(responses: FakeResponses) -> ArkResponsesFastModel:
    adapter = object.__new__(ArkResponsesFastModel)
    value = cast(Any, adapter)
    value._client = SimpleNamespace(responses=responses)
    value._model = "test-fast"
    value._prepare_lock = asyncio.Lock()
    return adapter


@pytest.mark.asyncio
async def test_voice_startup_uses_minimal_strict_json_compatibility_check() -> None:
    responses = FakeResponses()
    await _adapter(responses).prepare()

    assert len(responses.requests) == 1
    request = responses.requests[0]
    assert request["max_output_tokens"] == 32
    assert request["tools"] == []
    assert request["store"] is False
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    format_value = cast(dict[str, Any], cast(dict[str, Any], request["text"])["format"])
    assert format_value["type"] == "json_schema"
    assert format_value["strict"] is True
    assert cast(dict[str, Any], format_value["schema"])["additionalProperties"] is False


@pytest.mark.asyncio
async def test_voice_startup_rejects_model_without_exact_strict_result() -> None:
    with pytest.raises(LiveVoiceViolation, match="warmup failed") as captured:
        await _adapter(FakeResponses('{"ok":false}')).prepare()
    assert captured.value.code == "VOICE-LLM-PREPARE-FAILED"
