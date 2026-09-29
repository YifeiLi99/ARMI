import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from armi_cognition.api import autonomy_check_questions
from armi_kernel.application import (
    CredentialLocator,
    ModelViolation,
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_mood.api import JEV_MODEL
from armi_runtime.adapters.model.jev_autonomy import JevAutonomyCheck
from armi_runtime_foundation import DiagnosticLog, DiagnosticQuery


class Credentials:
    @contextmanager
    def resolve(self, locator, purpose):
        assert purpose.value == "autonomy.check"
        yield SimpleNamespace(consume=lambda read: read(b"isolated-test-key"))


def test_wake_request_excludes_history_and_keeps_existing_state():
    check = JevAutonomyCheck(
        credentials=cast(Any, Credentials()), locator=None, timeout_seconds=20
    )
    items = [
        {
            "item_kind": "mood",
            "content": json.dumps({"current": {"valence": 0.25, "arousal": 0.5}}),
        },
        {"item_kind": "recent_scene_turn", "content": "private dialogue" * 10000},
        {"item_kind": "self", "content": "private identity" * 10000},
    ]
    context = json.dumps({"layers": [{"items": items}]}).encode()
    request = check.request_evidence(context)
    assert len(request) <= 4096
    assert b"private dialogue" not in request
    assert b"private identity" not in request
    assert json.loads(request)["state"]["mood"] == {"valence": 0.25, "arousal": 0.5}
    assert json.loads(request)["state"]["drives"]["explore"] is None


def test_wake_request_growth_fails_before_provider(monkeypatch):
    monkeypatch.setattr(
        "armi_runtime.adapters.model.jev_autonomy.autonomy_check_questions",
        lambda available: {"accidental_growth": "x" * 4096},
    )
    check = JevAutonomyCheck(
        credentials=cast(Any, Credentials()), locator=None, timeout_seconds=20
    )
    with pytest.raises(ModelViolation, match="MODEL-JEV-CHECK-SIZE"):
        check.request_evidence(b'{"layers":[]}')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, 401, 429, 503, "timeout", "disconnect", "invalid_json"]
)
async def test_jev_check_is_single_metered_request_without_main_model(
    monkeypatch, failure
):
    calls, receipts = [], []
    raw = {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 120, "output_tokens": 10},
        "answers": {
            "category": {
                "type": "choice",
                "choice": "rest",
                "confidence": 1,
                "probabilities": {
                    key: int(key == "rest")
                    for key in autonomy_check_questions()["category"]["criteria"]
                },
            }
        },
    }

    def handler(request):
        calls.append(json.loads(request.content))
        assert request.url.path == "/v1/systemone"
        if failure == "timeout":
            raise httpx.ReadTimeout("isolated", request=request)
        if failure == "disconnect":
            raise httpx.RemoteProtocolError("isolated", request=request)
        if failure == "invalid_json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(failure or 200, json=raw)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(handler)),
    )

    async def save(receipt):
        receipts.append(receipt)

    check = JevAutonomyCheck(
        credentials=cast(Any, Credentials()),
        locator=CredentialLocator("env", "TEST_JEV"),
        timeout_seconds=20,
    )
    context = (
        b'{"layers":[{"items":[{"item_kind":"self","content":"existing interests"}]}]}'
    )
    request = check.request_evidence(context)
    with provider_meter_scope(
        ProviderMeterScope(save, PriceCatalog(()), "consider_autonomy_check")
    ):
        if failure is None:
            result = await check.invoke(request)
            assert result.response_bytes is not None
            assert json.loads(result.response_bytes) == raw
            assert result.provider_request_id is None
            assert result.usage is not None and result.usage.input_tokens == 120
            assert receipts[-1].cost.missing_usage == ()
        else:
            with pytest.raises(ModelViolation) as caught:
                await check.invoke(request)
            assert caught.value.outcome_unknown is (
                failure in {"timeout", "disconnect"}
            )
            if failure == 401:
                assert caught.value.code == "MODEL-AUTH-JEV"
    assert len(calls) == 1
    assert "context" not in calls[0]["state"]
    assert set(calls[0]["questions"]["category"]["criteria"]) == {
        "rest",
        "reflect",
        "explore",
        "unknown",
    }
    assert set(calls[0]["questions"]) == {"category"}
    assert len(receipts) >= 2
    assert len({receipt.call_id for receipt in receipts}) == 1
    assert receipts[0].registration and not receipts[-1].registration


@pytest.mark.asyncio
@pytest.mark.parametrize("first_error", [httpx.ConnectTimeout, httpx.ConnectError])
@pytest.mark.parametrize(
    "end", ["success", "connect_failure", "read_timeout", "cancel"]
)
async def test_connection_retry_is_bounded_metered_and_diagnosable(
    monkeypatch, tmp_path, first_error, end
):
    calls, receipts = [], []

    def handler(request):
        calls.append(request.content)
        assert request.extensions["timeout"] == {
            "connect": 3.0,
            "read": 20,
            "write": 20,
            "pool": 20,
        }
        if len(calls) == 1 or end == "connect_failure":
            raise first_error("isolated", request=request)
        if end == "read_timeout":
            raise httpx.ReadTimeout("isolated", request=request)
        return httpx.Response(
            200,
            json={
                "model": JEV_MODEL,
                "usage": {"input_tokens": 120, "output_tokens": 10},
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    delay = AsyncMock(side_effect=asyncio.CancelledError if end == "cancel" else None)
    monkeypatch.setattr(
        "armi_runtime.adapters.model.jev_transport.asyncio.sleep", delay
    )

    async def save(receipt):
        receipts.append(receipt)

    check = JevAutonomyCheck(
        credentials=cast(Any, Credentials()),
        locator=CredentialLocator("env", "TEST_JEV"),
        timeout_seconds=20,
    )
    sink = DiagnosticLog(data_root=tmp_path, environment_id="test", instance_id="test")
    sink.install()
    try:
        with provider_meter_scope(
            ProviderMeterScope(save, PriceCatalog(()), "consider_autonomy_check")
        ):
            if end == "success":
                result = await check.invoke(b'{"frozen":true}')
                assert result.usage is not None and result.usage.input_tokens == 120
            elif end == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await check.invoke(b'{"frozen":true}')
            else:
                with pytest.raises(ModelViolation) as caught:
                    await check.invoke(b'{"frozen":true}')
                assert caught.value.outcome_unknown is (end == "read_timeout")
                if end == "connect_failure":
                    assert caught.value.code == (
                        "MODEL-JEV-CONNECT-TIMEOUT"
                        if first_error is httpx.ConnectTimeout
                        else "MODEL-JEV-CONNECT-FAILED"
                    )
    finally:
        sink.close()
    delay.assert_awaited_once_with(0.5)
    assert calls == [b'{"frozen":true}'] * (1 if end == "cancel" else 2)
    final = {row.call_id: row for row in receipts}
    assert len(final) == len(calls)
    first = next(iter(final.values()))
    assert first.outcome == "failed" and not first.billable
    assert first.cost.status.value == "not_billable"
    if len(final) == 2:
        assert receipts[-1].parent_call_id == first.call_id
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="test").query()
    errors = [row for row in page["items"] if row["event"] == "provider.call.failed"]
    assert errors[0]["phase"] == "connect"
    assert errors[0]["error_type"] == first_error.__name__
    assert errors[0]["request_delivery"] == "not_sent"
    assert errors[0]["transport_attempt"] == 1
    assert errors[0]["retry_scheduled"] is True
    if end in {"connect_failure", "read_timeout"}:
        assert errors[-1]["transport_attempt"] == 2
        assert errors[-1]["retry_scheduled"] is False
    assert "isolated-test-key" not in json.dumps(page)
