from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from armi_live_voice.api import VoiceContext
from armi_runtime.adapters.voice.ark import ArkResponsesFastModel


class FakeResponses:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object):
        self.requests.append(request)

        async def events():
            yield SimpleNamespace(type="response.output_text.delta", delta="SPEAK\n")
            yield SimpleNamespace(type="response.output_text.delta", delta="好。")

        return events()


@pytest.mark.asyncio
async def test_fast_model_uses_real_protocol_newlines_and_low_latency_options() -> None:
    adapter = object.__new__(ArkResponsesFastModel)
    uninitialized = cast(Any, adapter)
    responses = FakeResponses()
    uninitialized._client = SimpleNamespace(responses=responses)
    uninitialized._model = "test-fast"
    uninitialized._prepare_lock = asyncio.Lock()

    await adapter.prepare()

    output = "".join(
        [
            delta
            async for delta in adapter.generate(
                VoiceContext("1", "compact context"), "你好"
            )
        ]
    )

    assert output == "SPEAK\n好。"
    assert len(responses.requests) == 2
    warmup, request = responses.requests
    assert warmup["max_output_tokens"] == 8
    assert warmup["stream"] is True
    instruction = request["instructions"]
    assert isinstance(instruction, str)
    assert "首行从SPEAK/WAIT/SILENT三选一" in instruction
    assert "SPEAK第二行一句回答(最多60字)" in instruction
    assert "SPEAK\\n" not in instruction
    assert request["max_output_tokens"] == 96
    assert request["stream"] is True
    assert request["tools"] == []
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
