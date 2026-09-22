"""Jev is a single factual appraisal call under an independently metered scope."""

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid7

import httpx
import pytest
from armi_kernel.application import (
    CredentialLocator,
    PriceCatalog,
    ProviderMeterScope,
    provider_meter_scope,
)
from armi_mood.api import (
    JEV_MODEL,
    DynamicsParameters,
    MoodAssessment,
    MoodEvent,
    MoodViolation,
    initial_dynamics,
)
from armi_runtime.adapters.model.jev import JevAppraiser


class Credentials:
    @contextmanager
    def resolve(self, locator, purpose):
        assert purpose.value == "mood.appraisal"
        yield SimpleNamespace(consume=lambda read: read(b"test-only-secret"))


@pytest.mark.parametrize("status", [200, 429, 503, 302])
def test_jev_once_with_no_redirect_or_fallback(monkeypatch, status):
    now = datetime.now(UTC)
    event = MoodEvent("e:1", uuid7(), uuid7(), uuid7(), 1, now, "Synthetic event")
    assessment = MoodAssessment(
        uuid7(), event, "new", 1, initial_dynamics(now, DynamicsParameters())
    )
    calls, receipts = [], []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == JEV_MODEL
        assert "sadness" not in body["questions"]
        assert body["state"]["context"] == []
        answers = {
            key: {
                "type": "choice",
                "choice": "unknown",
                "confidence": 1,
                "probabilities": {
                    name: int(name == "unknown") for name in question["criteria"]
                },
            }
            for key, question in body["questions"].items()
        }
        return httpx.Response(
            status,
            json={
                "model": JEV_MODEL,
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(handler)),
    )

    async def save(receipt):
        receipts.append(receipt)

    async def run():
        appraiser = JevAppraiser(
            credentials=cast(Any, Credentials()),
            locator=CredentialLocator("env", "JEV_TEST_KEY"),
            timeout_seconds=20,
        )
        with provider_meter_scope(
            ProviderMeterScope(save, PriceCatalog(()), "mood.evaluate")
        ):
            return await appraiser.evaluate(
                assessment=assessment,
                context={
                    "layers": [
                        {
                            "items": [
                                {
                                    "item_kind": "mood",
                                    "content": "private computed emotion",
                                },
                                {
                                    "item_kind": "subject_prompt",
                                    "content": "instruction",
                                },
                            ]
                        }
                    ]
                },
            )

    if status == 200:
        result = asyncio.run(run())
        assert result.appraisal.loss is None
        assert result.input_tokens == 100
    else:
        with pytest.raises(MoodViolation):
            asyncio.run(run())
    assert len(calls) == 1
    assert receipts[0].registration


def test_missing_jev_key_cannot_dispatch():
    appraiser = JevAppraiser(
        credentials=cast(Any, Credentials()), locator=None, timeout_seconds=20
    )
    with pytest.raises(MoodViolation, match="MOOD-JEV-CREDENTIAL-MISSING"):
        asyncio.run(appraiser.evaluate(assessment=cast(Any, None), context={}))
