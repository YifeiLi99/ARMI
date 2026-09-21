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
from armi_runtime.adapters.model import structured as ark
from armi_runtime.composition.model_verification import (
    GENERIC_COGNITION_INSTRUCTIONS,
    candidate_schema,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["consider_codex_task", "consider_codex_result"])
async def test_generic_transport_sends_current_prompt_and_schema(
    monkeypatch, purpose
) -> None:
    response = SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[])],
        id="controlled-response",
        model="doubao-seed-evolving",
        output_text="{}",
        usage=None,
        model_dump=lambda **_kwargs: {},
    )
    create = AsyncMock(
        return_value=SimpleNamespace(headers={}, parse=AsyncMock(return_value=response))
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )
    clients = ark.ModelClients()
    monkeypatch.setattr(clients, "get", lambda *_args: client)
    schema = candidate_schema("armi.cognition-candidate")
    transport = ark.OfficialArkTransport(
        schema,
        clients=clients,
        instructions=GENERIC_COGNITION_INSTRUCTIONS,
        schema_name="armi_cognition_candidate_v13",
    )
    request = SimpleNamespace(
        canonical_bytes=json.dumps(
            {
                "schema_kind": "armi.model-request",
                "compiled_context": {
                    "purpose": purpose,
                    "layers": [
                        {
                            "items": [
                                {
                                    "item_kind": "current_evidence",
                                    "content": "受托研究结果",
                                }
                            ]
                        }
                    ],
                },
                "included_context_refs": [{"ref": "ctx:1"}],
            }
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
                    provider="volcengine_ark",
                    model_id="doubao-seed-evolving",
                    response_contract_kind="armi.cognition-candidate",
                ),
            ),
            request=cast(Any, request),
        )
    assert receipts[-1].provider_request_id == "controlled-response"
    assert receipts[-1].outcome == "returned"
    assert create.await_args is not None
    payload = create.await_args.kwargs
    assert payload == transport.request_parameters(
        cast(
            Any,
            SimpleNamespace(
                model_id="doubao-seed-evolving",
                response_contract_kind="armi.cognition-candidate",
            ),
        ),
        cast(Any, request),
    )
    assert payload["instructions"].startswith("# ARMI 本轮认知\n\n## 基本规则")
    assert "候选放在 candidate 属性中" in payload["instructions"]
    assert payload["text"]["format"]["schema"]["required"] == ["candidate"]
    assert "受托研究结果" in payload["input"][-1]["content"]
    assert payload["text"]["format"]["name"] == "armi_cognition_candidate_v13"
    wire = json.dumps(payload["text"]["format"]["schema"])
    assert "capability_request" not in wire
    assert "permission_grant" not in wire
    assert "codex_delegation" in wire
    client.close.assert_not_awaited()
