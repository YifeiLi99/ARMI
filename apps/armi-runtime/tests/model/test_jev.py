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
from armi_mind.api import GroundedObject, MindEvaluationTarget
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
            ProviderMeterScope(save, PriceCatalog(()), "event.appraise")
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


@pytest.mark.parametrize("bad_owner", [None, "mind", "mood"])
def test_joint_event_uses_one_dispatch_and_preserves_valid_owner(
    monkeypatch, bad_owner
):
    now = datetime.now(UTC)
    event = MoodEvent("e:1", uuid7(), uuid7(), uuid7(), 1, now, "Synthetic event")
    assessment = MoodAssessment(
        uuid7(), event, "new", 1, initial_dynamics(now, DynamicsParameters())
    )
    target = MindEvaluationTarget(
        GroundedObject("event", str(event.source_ref)), (str(event.source_ref),)
    )
    calls, receipts = [], []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        answers = {
            name: {
                "type": "choice",
                "choice": "unknown",
                "confidence": 1,
                "probabilities": {
                    option: int(option == "unknown") for option in question["criteria"]
                },
            }
            for name, question in body["questions"].items()
        }
        if bad_owner is not None:
            answers.pop("gain" if bad_owner == "mood" else "mind_0_contact_gap")
        return httpx.Response(
            200,
            json={
                "model": JEV_MODEL,
                "answers": answers,
                "usage": {"input_tokens": 111, "output_tokens": 22},
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
            ProviderMeterScope(save, PriceCatalog(()), "event.evaluate")
        ):
            return await appraiser.evaluate_event(
                assessment=assessment, context={"layers": []}, targets=(target,)
            )

    result = asyncio.run(run())
    assert len(calls) == 1
    assert sum(receipt.registration for receipt in receipts) == 1
    assert result.input_tokens == 111
    assert result.ready_for_cognition == (bad_owner is None)
    assert (result.mind is None) == (bad_owner == "mind")
    assert (result.mood is None) == (bad_owner == "mood")
    assert len([key for key in calls[0]["questions"] if key.startswith("mind_")]) == 18


def test_joint_event_rejects_target_outside_frozen_context():
    now = datetime.now(UTC)
    event = MoodEvent("e:1", uuid7(), uuid7(), uuid7(), 1, now, "Synthetic event")
    assessment = MoodAssessment(
        uuid7(), event, "new", 1, initial_dynamics(now, DynamicsParameters())
    )
    target = MindEvaluationTarget(GroundedObject("party", str(uuid7())), ("invented",))
    appraiser = JevAppraiser(
        credentials=cast(Any, Credentials()),
        locator=CredentialLocator("env", "JEV_TEST_KEY"),
        timeout_seconds=20,
    )
    with pytest.raises(MoodViolation, match="SOURCE-FORBIDDEN"):
        asyncio.run(
            appraiser.evaluate_event(
                assessment=assessment, context={"layers": []}, targets=(target,)
            )
        )
