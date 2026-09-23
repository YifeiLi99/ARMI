import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast

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


class Credentials:
    @contextmanager
    def resolve(self, locator, purpose):
        assert purpose.value == "autonomy.check"
        yield SimpleNamespace(consume=lambda read: read(b"isolated-test-key"))


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
                "choice": "wait",
                "confidence": 1,
                "probabilities": {
                    key: int(key == "wait")
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
        else:
            with pytest.raises(ModelViolation) as caught:
                await check.invoke(request)
            assert caught.value.outcome_unknown is (
                failure in {"timeout", "disconnect"}
            )
            if failure == 401:
                assert caught.value.code == "MODEL-AUTH-JEV"
    assert len(calls) == 1
    assert calls[0]["state"]["context"] == json.loads(context)
    assert set(calls[0]["questions"]) == {"category"}
    assert len(receipts) >= 2
    assert len({receipt.call_id for receipt in receipts}) == 1
    assert receipts[0].registration and not receipts[-1].registration
