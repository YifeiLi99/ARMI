from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from armi_kernel.application import (
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_live_voice.api import LiveVoiceViolation
from armi_runtime.adapters.voice.ark import ArkResponsesFastModel


@pytest.fixture(autouse=True)
def fake_provider_receipts():
    """These adapter tests use fake transports and an inspectable receipt sink."""
    receipts = []

    async def save(receipt):
        receipts.append(receipt)

    with provider_meter_scope(
        ProviderMeterScope(save, PriceCatalog(()), "adapter_test")
    ):
        yield receipts


class FakeResponses:
    def __init__(self, output_text: str = '{"ok":true}') -> None:
        self.output_text = output_text
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object):
        self.requests.append(request)
        return SimpleNamespace(
            output_text=self.output_text,
            id="warmup-response",
            model="test-fast",
            model_dump=lambda **_: {"usage": {"input_tokens": 10, "output_tokens": 4}},
        )


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
async def test_voice_startup_rejects_model_without_exact_strict_result(
    fake_provider_receipts,
) -> None:
    with pytest.raises(LiveVoiceViolation, match="warmup failed") as captured:
        await _adapter(FakeResponses('{"ok":false}')).prepare()
    assert captured.value.code == "VOICE-LLM-PREPARE-FAILED"
    receipt = fake_provider_receipts[-1]
    assert receipt.outcome == "returned"
    assert receipt.provider_request_id == "warmup-response"
    assert {item.unit.value: item.quantity for item in receipt.quantities} == {
        "input_tokens": 10,
        "output_tokens": 4,
    }


@pytest.mark.asyncio
async def test_voice_compatibility_registration_failure_sends_no_request():
    responses = FakeResponses()

    async def reject(_receipt):
        raise OSError("receipt storage unavailable")

    with (
        provider_meter_scope(
            ProviderMeterScope(reject, PriceCatalog(()), "compatibility")
        ),
        pytest.raises(LiveVoiceViolation),
    ):
        await _adapter(responses).prepare()
    assert responses.requests == []
