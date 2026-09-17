"""The real Ark transport receives Cognition's current business contract."""

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from armi_kernel.application import (
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_runtime.adapters.model import volcengine_ark as ark
from armi_runtime.composition.model_verification import (
    GENERIC_COGNITION_INSTRUCTIONS,
    candidate_schema,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose", ["consider_codex_task", "consider_codex_result", "consider_web_evidence"]
)
async def test_generic_transport_sends_current_prompt_and_schema(
    monkeypatch, purpose
) -> None:
    response = SimpleNamespace(
        output=[SimpleNamespace(type="message")],
        id="controlled-response",
        model="doubao-seed-evolving",
        output_text="{}",
        usage=None,
        model_dump=lambda **_kwargs: {},
    )
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        responses=SimpleNamespace(create=create), close=AsyncMock()
    )
    monkeypatch.setattr(ark, "_client", lambda *_args: client)
    schema = candidate_schema("armi.cognition-candidate.v16")
    transport = ark.OpenAIArkTransport(
        schema,
        instructions=GENERIC_COGNITION_INSTRUCTIONS,
        schema_name="armi_cognition_candidate_v13",
    )
    request = SimpleNamespace(
        canonical_bytes=json.dumps(
            {"purpose": purpose, "included_context_refs": [{"ref": "ctx:1"}]}
        ).encode(),
        max_output_tokens=1024,
    )
    receipts = []

    async def save(receipt):
        receipts.append(receipt)

    with provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), purpose)):
        await transport.invoke(
            api_key=memoryview(b"isolated-test"),
            binding=cast(
                Any,
                SimpleNamespace(
                    provider="volcengine_ark", model_id="doubao-seed-evolving"
                ),
            ),
            request=cast(Any, request),
        )
    assert receipts[-1].provider_request_id == "controlled-response"
    assert receipts[-1].outcome == "returned"
    assert create.await_args is not None
    payload = create.await_args.kwargs
    assert payload == transport.request_parameters(
        cast(Any, SimpleNamespace(model_id="doubao-seed-evolving")), cast(Any, request)
    )
    assert payload["instructions"].startswith(GENERIC_COGNITION_INSTRUCTIONS)
    assert "candidate object property" in payload["instructions"]
    assert payload["text"]["format"]["schema"]["required"] == ["candidate"]
    assert purpose in payload["input"]
    assert payload["text"]["format"]["name"] == "armi_cognition_candidate_v13"
    wire = json.dumps(payload["text"]["format"]["schema"])
    assert "capability_request" not in wire
    assert "permission_grant" not in wire
    assert "codex_delegation" in wire
    client.close.assert_awaited_once()
