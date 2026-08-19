from __future__ import annotations

from types import SimpleNamespace

import pytest
from armi_live_voice.api import VoiceContext
from armi_runtime.adapters.voice.ark import ArkResponsesFastModel


class FakeResponses:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    async def create(self, **request: object):
        self.request = request

        async def events():
            yield SimpleNamespace(type="response.output_text.delta", delta="SPEAK\n")
            yield SimpleNamespace(type="response.output_text.delta", delta="好。")

        return events()


@pytest.mark.asyncio
async def test_fast_model_uses_real_protocol_newlines_and_low_latency_options() -> None:
    adapter = object.__new__(ArkResponsesFastModel)
    responses = FakeResponses()
    adapter._client = SimpleNamespace(responses=responses)
    adapter._model = "test-lite"

    output = "".join(
        [
            delta
            async for delta in adapter.generate(
                VoiceContext("1", "compact context"), "你好"
            )
        ]
    )

    assert output == "SPEAK\n好。"
    assert responses.request is not None
    instruction = responses.request["instructions"]
    assert isinstance(instruction, str)
    assert "SPEAK\n<一至两句、最多160字>" in instruction
    assert "SPEAK\\n" not in instruction
    assert responses.request["stream"] is True
    assert responses.request["tools"] == []
    assert responses.request["extra_body"] == {"thinking": {"type": "disabled"}}
