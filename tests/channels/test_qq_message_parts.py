"""Ordered QQ delivery preserves receipts and stops at any failed boundary."""

# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_adapter_qq import QQAdapterConfig, QQEffectAdapter, QQEgressAdapter
from armi_channel_napcat import NapCatActionResponse, NapCatAmbiguousDelivery
from armi_effect.api import (
    EffectAttemptId,
    EffectId,
    EffectViolation,
    FrozenEffectRequest,
)
from armi_kernel.application import ModelRequest
from armi_kernel.contracts import Digest, TraceId
from armi_runtime.adapters.model.compatible import CompatibleStructuredTransport
from armi_runtime.composition.model_verification import (
    candidate_schema,
    load_purpose_binding,
    model_response_candidate,
    parse_candidate,
)
from armi_runtime.composition.postgresql_test import (
    bootstrap_effect_runtime,
    compose_effect_dispatch_repository,
)
from jsonschema import Draft202012Validator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose",
    [
        "consider_creator_input",
        "consider_other_human_input",
        "consider_autonomous_life",
    ],
)
@pytest.mark.parametrize(
    "messages", [["嗯"], ["嗯", "我在呀"], ["嗯", "我在呀", "怎么啦？"]]
)
async def test_model_messages_become_exact_qq_sends(purpose, messages):
    selected = load_purpose_binding(purpose)
    renderer = CompatibleStructuredTransport(
        candidate_schema(selected.response_contract_version, purpose=purpose),
        instructions="",
        schema_name="test",
    )
    request_body = b'{"included_context_refs":[]}'
    schema = renderer.output_format(
        ModelRequest(request_body, Digest.from_bytes(request_body), 1, 2048)
    )["schema"]
    autonomous = purpose == "consider_autonomous_life"
    wire = (
        {
            "candidate": {
                "kind": "no_activity",
                "expression": messages,
                "next_consideration_seconds": 300,
            }
        }
        if autonomous
        else {"action": "reply", "content": messages}
    )
    Draft202012Validator(schema).validate(wire)
    native = model_response_candidate(
        json.dumps(
            {
                "schema_version": "armi.model-response-artifact.v3",
                "output_text": json.dumps(wire),
            }
        ).encode(),
        expected_version=selected.response_contract_version,
    )
    parsed = parse_candidate(
        json.dumps(native).encode(),
        expected_version=selected.response_contract_version,
        allowed_context_refs=frozenset(),
    )
    decoded = cast(Any, parsed)
    content = decoded.expression if autonomous else decoded.decision.content
    sent = []

    class Gateway:
        async def send_private_text(self, *, user_id, text, echo):
            sent.append(text)
            return NapCatActionResponse("ok", 0, str(len(sent)), echo)

    adapter = QQEffectAdapter(
        QQEgressAdapter(
            config=QQAdapterConfig(10001, 90009, {}, frozenset()),
            gateway=cast(Any, Gateway()),
        )
    )
    payload = content.encode("utf-8")
    request = FrozenEffectRequest(
        EffectId(uuid7()),
        EffectAttemptId(uuid7()),
        uuid7(),
        uuid7(),
        uuid7(),
        "external_private",
        "qq",
        "10001",
        "90009",
        Digest.from_bytes(payload),
        len(payload),
        TraceId(uuid7().hex),
    )
    for part in adapter.payload_parts(request, payload):
        await adapter.dispatch(request, part)
    assert sent == messages


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "unknown",
        "stop",
        "runtime",
        "rights",
        "claim",
        "route",
        "storage",
        "cancel",
    ],
)
async def test_sequential_delivery_retains_receipts_and_never_resumes(
    failure: str | None,
) -> None:
    sent: list[str] = []
    saved: list[str] = []
    fence = object()
    state = SimpleNamespace(runtime_fence=fence, transaction=object())
    pipeline: Any = None

    class Gateway:
        async def send_private_text(self, *, user_id: int, text: str, echo: str):
            assert user_id == 90009
            if sent:
                assert saved == ["101"] if len(sent) == 1 else saved == ["101", "102"]
            sent.append(text)
            if failure == "unknown" and len(sent) == 2:
                raise NapCatAmbiguousDelivery("NAPCAT-DELIVERY-AMBIGUOUS")
            if failure == "cancel" and len(sent) == 2:
                raise asyncio.CancelledError
            return NapCatActionResponse("ok", 0, str(100 + len(sent)), echo)

    @asynccontextmanager
    async def unit_of_work():
        yield state

    async def record_part(uow, snapshot, receipt, *, index, total):
        assert total == 3
        assert index == len(saved)
        if failure == "storage":
            raise EffectViolation("EFFECT-RECEIVER-CONFLICT")
        saved.append(receipt.external_receiver_ref)
        if failure == "stop":
            pipeline.stop()
        if failure == "runtime":
            state.runtime_fence = object()

    rights = AsyncMock()
    claims = AsyncMock()
    if failure == "rights":
        rights.validate.side_effect = EffectViolation("EFFECT-DATA-RIGHTS-BLOCKED")
    if failure == "claim":
        claims.renew_claim.side_effect = EffectViolation("EFFECT-CLAIM-STALE")
    if failure == "route":
        claims.validate_message_route.side_effect = EffectViolation(
            "EFFECT-DESTINATION-UNAVAILABLE"
        )
    claims.record_message_part.side_effect = record_part
    adapter = QQEffectAdapter(
        QQEgressAdapter(
            config=QQAdapterConfig(10001, 90009, {}, frozenset()),
            gateway=cast(Any, Gateway()),
        )
    )
    placeholder = cast(Any, SimpleNamespace())
    pipeline = bootstrap_effect_runtime(
        factory=cast(Any, SimpleNamespace(unit_of_work=unit_of_work)),
        storage=placeholder,
        intents=placeholder,
        codex_artifacts=placeholder,
        routes=placeholder,
        interaction_delivery=placeholder,
        custody=placeholder,
        data_rights=placeholder,
        data_rights_fence=rights,
        runtime_admission=cast(Any, lambda: fence),
        external_message_adapter=adapter,
    )
    pipeline._dispatcher = claims
    content = "嗯\n\n我在呀\n\n怎么啦？".encode()
    request = FrozenEffectRequest(
        EffectId(uuid7()),
        EffectAttemptId(uuid7()),
        uuid7(),
        uuid7(),
        uuid7(),
        "external_private",
        "qq",
        "10001",
        "90009",
        Digest.from_bytes(content),
        len(content),
        TraceId(uuid7().hex),
    )
    snapshot = SimpleNamespace(request=request)
    if failure is None:
        receipt = await pipeline._dispatch_parts(snapshot, content, fence, placeholder)
        assert receipt.external_receiver_ref == "103"
        assert sent == ["嗯", "我在呀", "怎么啦？"]
        assert saved == ["101", "102"]
        assert rights.validate.await_count == 2
    else:
        with pytest.raises((EffectViolation, asyncio.CancelledError)):
            await pipeline._dispatch_parts(snapshot, content, fence, placeholder)
        assert sent == (
            ["嗯", "我在呀"] if failure in {"unknown", "cancel"} else ["嗯"]
        )
        assert saved == ([] if failure == "storage" else ["101"])


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["90009", "90010"])
async def test_later_part_checks_current_interaction_target(target: str) -> None:
    routes = AsyncMock()
    routes.effect_route.return_value = SimpleNamespace(
        external_channel="qq",
        external_account_key="10001",
        external_conversation_key=target,
    )
    dispatcher = compose_effect_dispatch_repository(routes)
    request = SimpleNamespace(
        scene_id=uuid7(),
        destination_party_id=uuid7(),
        destination_kind="external_private",
        external_channel="qq",
        external_account_key="10001",
        external_conversation_key="90009",
    )
    uow = cast(Any, SimpleNamespace(transaction=object()))
    snapshot = cast(Any, SimpleNamespace(request=request))
    if target == "90009":
        await dispatcher.validate_message_route(uow, snapshot)
    else:
        with pytest.raises(EffectViolation, match="EFFECT-DESTINATION-UNAVAILABLE"):
            await dispatcher.validate_message_route(uow, snapshot)
