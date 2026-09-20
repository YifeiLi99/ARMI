"""Official SDK wire contract, reuse, shutdown and content-free diagnostics."""

import json
import ssl
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from arkruntime import AsyncArk
from arkruntime._exceptions import ArkAPIConnectionError, ArkAPIStatusError
from armi_kernel.application import (
    ModelViolation,
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_runtime.adapters.model import model_clients
from armi_runtime.adapters.model.structured import OfficialArkTransport


def binding():
    return cast(
        Any,
        SimpleNamespace(
            api_base="https://ark.example/api/v3",
            timeout_seconds=180,
            provider="volcengine_ark",
            model_id="doubao-seed-evolving",
        ),
    )


@pytest.mark.asyncio
async def test_official_sdk_reuses_client_across_contexts_and_preserves_wire(
    monkeypatch,
):
    requests = []
    clients = []
    receipts = []

    async def respond(request):
        requests.append(request)
        if request.url.path.endswith("/tokenization"):
            return httpx.Response(
                200,
                headers={"x-request-id": "token-request"},
                json={
                    "id": "tokens",
                    "object": "list",
                    "created": 1,
                    "model": "doubao-seed-evolving",
                    "data": [
                        {
                            "index": 0,
                            "object": "tokenization",
                            "total_tokens": 6,
                            "token_ids": [1],
                            "offset_mapping": [[0, 1]],
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            headers={"x-request-id": "generation-request"},
            json={
                "id": "response",
                "object": "response",
                "created_at": 1,
                "model": "doubao-seed-evolving",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"candidate":{}}',
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 6,
                    "output_tokens": 5,
                    "total_tokens": 11,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    def make_client(**kwargs):
        assert kwargs["max_retries"] == 0
        assert kwargs["timeout"] == 180
        # Use the real official SDK and the same hooks, replacing only network I/O.
        http = kwargs["http_client"]
        http._transport = httpx.MockTransport(respond)
        client = AsyncArk(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(model_clients, "AsyncArk", make_client)

    async def record(receipt):
        receipts.append(receipt)

    request = cast(
        Any,
        SimpleNamespace(
            canonical_bytes=json.dumps(
                {
                    "schema_version": "armi.model-request.v1",
                    "compiled_context": {
                        "purpose": "consider_other_human_input",
                        "layers": [],
                    },
                    "included_context_refs": [],
                }
            ).encode(),
            max_output_tokens=2048,
        ),
    )
    async with model_clients.ModelClients() as pool:
        for name in ("first_context", "second_context"):
            transport = OfficialArkTransport(
                {"type": "object", "properties": {}, "$defs": {}},
                instructions="test",
                schema_name=name,
                clients=pool,
            )
            with provider_meter_scope(
                ProviderMeterScope(record, PriceCatalog(()), "test")
            ):
                assert (
                    await transport.tokenize(
                        api_key=memoryview(b"test-key"),
                        binding=binding(),
                        request_bytes=request.canonical_bytes,
                    )
                    == 6
                )
                response = await transport.invoke(
                    api_key=memoryview(b"test-key"), binding=binding(), request=request
                )
            assert response["output_text"] == '{"candidate":{}}'
            assert response["usage"]["input_tokens"] == 6
            assert not clients[0].is_closed()
        assert len(clients) == 1
        assert len(requests) == 4
        for request in requests:
            assert request.extensions["timeout"]["connect"] == 180
            assert request.headers["authorization"] == "Bearer test-key"
            body = json.loads(request.content)
            if request.url.path.endswith("/responses"):
                assert body["text"]["format"]["strict"] is True
                assert body["store"] is False
                assert body["thinking"] == {"type": "disabled"}
        assert any(r.provider_request_id == "token-request" for r in receipts)
    assert clients[0].is_closed()
    await pool.close()
    with pytest.raises(ModelViolation, match="MODEL-CLIENT-CLOSED"):
        pool.get(memoryview(b"test-key"), binding())


@pytest.mark.asyncio
async def test_credential_rotation_does_not_mutate_inflight_client():
    async with model_clients.ModelClients() as pool:
        first = pool.get(memoryview(b"first-key"), binding())
        second = pool.get(memoryview(b"second-key"), binding())
        assert first is not second
        assert first.api_key == "first-key"
        assert second.api_key == "second-key"
        assert pool.get(memoryview(b"second-key"), binding()) is second
    assert first.is_closed() and second.is_closed()


@pytest.mark.asyncio
async def test_tls_diagnostic_keeps_cause_and_never_logs_messages():
    events = []
    async with model_clients.ModelClients(lambda *args: events.append(args)) as pool:
        request = httpx.Request(
            "POST",
            "https://ark.example/api/v3/tokenization",
            headers={"Authorization": "Bearer PRIVATE"},
            content=b"PRIVATE PROMPT",
        )
        await pool._on_request(request)
        cause = ssl.SSLEOFError("PRIVATE ERROR BODY")
        error = httpx.ConnectError("PRIVATE URL", request=request)
        error.__cause__ = cause
        await request.extensions["trace"](
            "connection.start_tls.failed", {"exception": error}
        )
    assert events[0][0] == "model.ark.tokenization.connection.start_tls.failed"
    assert events[0][2] == ("EXCEPTION-CONNECTERROR", "EXCEPTION-SSLEOFERROR")
    assert "PRIVATE" not in repr(events)


@pytest.mark.asyncio
async def test_connection_failure_has_no_hidden_sdk_retry(monkeypatch):
    calls = 0

    async def fail(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("controlled", request=request)

    async with model_clients.ModelClients() as pool:
        client = pool.get(memoryview(b"test-key"), binding())
        client._client._transport = httpx.MockTransport(fail)
        with pytest.raises(ArkAPIConnectionError):
            await client.tokenization.create(model="doubao-seed-evolving", text="test")
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 503])
async def test_http_rejection_preserves_request_id_and_failed_receipt(status):
    receipts = []

    async def record(receipt):
        receipts.append(receipt)

    async with model_clients.ModelClients() as pool:
        client = pool.get(memoryview(b"test-key"), binding())
        client._client._transport = httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                headers={"x-request-id": "rejected-request"},
                json={"error": {"code": "controlled", "message": "PRIVATE"}},
            )
        )
        transport = OfficialArkTransport(
            {"type": "object", "properties": {}},
            instructions="test",
            schema_name="test",
            clients=pool,
        )
        with (
            provider_meter_scope(ProviderMeterScope(record, PriceCatalog(()), "test")),
            pytest.raises(ArkAPIStatusError),
        ):
            await transport.tokenize(
                api_key=memoryview(b"test-key"),
                binding=binding(),
                request_bytes=b'{"schema_version":"armi.model-request.v1","compiled_context":{"purpose":"consider_other_human_input","layers":[]},"included_context_refs":[]}',
            )
    assert receipts[-1].outcome == "failed"
    assert receipts[-1].provider_request_id == "rejected-request"
    assert receipts[-1].error_code == f"USAGE-PROVIDER-HTTP-{status}"
    assert "PRIVATE" not in repr(receipts)
