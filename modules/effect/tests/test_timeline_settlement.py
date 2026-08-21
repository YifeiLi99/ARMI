from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid7

import pytest
from armi_effect._application import EffectRegistrationPipeline
from armi_effect._dispatch import EffectDispatchSnapshot
from armi_effect.api import (
    EffectAdapterReceipt,
    EffectAttemptId,
    EffectDeliveryId,
    EffectId,
    EffectViolation,
    FrozenEffectRequest,
)
from armi_kernel.contracts import Digest, Instant, TraceId


class _UnitOfWork:
    transaction = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        del args


def _pipeline(*, receipt: EffectAdapterReceipt | None) -> Any:
    pipeline = cast(Any, object.__new__(EffectRegistrationPipeline))
    pipeline._factory = SimpleNamespace(unit_of_work=lambda **_kwargs: _UnitOfWork())
    pipeline._dispatcher = AsyncMock()
    pipeline._adapter = AsyncMock()
    pipeline._adapter.observe.return_value = receipt
    pipeline._interaction_delivery = AsyncMock()
    pipeline._diagnostic = Mock()
    pipeline._stop = Mock()
    pipeline._stop.is_set.return_value = False
    return pipeline


def _snapshot() -> EffectDispatchSnapshot:
    content = b"reply"
    request = FrozenEffectRequest(
        EffectId(uuid7()),
        EffectAttemptId(uuid7()),
        uuid7(),
        uuid7(),
        uuid7(),
        "external_private",
        "qq",
        "account",
        "friend",
        Digest.from_bytes(content),
        len(content),
        TraceId(uuid7().hex),
    )
    return EffectDispatchSnapshot(uuid7(), uuid7(), 1, 1, uuid7(), "default", request)


def _receipt() -> EffectAdapterReceipt:
    return EffectAdapterReceipt(
        EffectDeliveryId(uuid7()),
        Digest.from_bytes(b"receipt"),
        Instant(datetime.now(UTC)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("destination", "route"),
    (
        ("creator_inbox", (None, None, None)),
        ("other_human_inbox", (None, None, None)),
        ("external_private", ("qq", "account", "friend")),
        ("external_group", ("qq", "account", "group")),
    ),
)
async def test_verified_receipt_records_every_party_destination(
    destination: str, route: tuple[str | None, str | None, str | None]
) -> None:
    content = b"reply"
    request = FrozenEffectRequest(
        EffectId(uuid7()),
        EffectAttemptId(uuid7()),
        uuid7(),
        uuid7(),
        uuid7(),
        destination,  # type: ignore[arg-type]
        *route,
        Digest.from_bytes(content),
        len(content),
        TraceId(uuid7().hex),
    )
    snapshot = EffectDispatchSnapshot(
        uuid7(), uuid7(), 1, 1, uuid7(), "default", request
    )
    receipt = EffectAdapterReceipt(
        EffectDeliveryId(uuid7()),
        Digest.from_bytes(b"receipt"),
        Instant(datetime.now(UTC)),
    )
    timeline = AsyncMock()
    pipeline = object.__new__(EffectRegistrationPipeline)
    pipeline._interaction_delivery = timeline
    transaction = object()

    await pipeline._record_party_response(
        SimpleNamespace(transaction=transaction),  # type: ignore[arg-type]
        snapshot,
        receipt,
    )

    timeline.record_party_response.assert_awaited_once_with(
        transaction,
        scene_id=request.scene_id,
        effect_id=request.effect_id.value,
        occurred_at=receipt.received_at,
    )


@pytest.mark.asyncio
async def test_crash_reconciliation_records_verified_receipt() -> None:
    snapshot = _snapshot()
    receipt = _receipt()
    pipeline = _pipeline(receipt=receipt)

    assert await pipeline._reconcile(snapshot) is True

    pipeline._dispatcher.settle_receipt.assert_awaited_once()
    pipeline._interaction_delivery.record_party_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_recovery_records_later_verified_receipt() -> None:
    snapshot = _snapshot()
    receipt = _receipt()
    pipeline = _pipeline(receipt=receipt)
    pipeline._dispatcher.expired.return_value = None
    pipeline._dispatcher.unknown.return_value = snapshot

    assert await pipeline.recover_once() is True

    pipeline._dispatcher.resolve_unknown_receipt.assert_awaited_once()
    pipeline._interaction_delivery.record_party_response.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verification", (None, EffectViolation("EFFECT-RESULT-UNKNOWN"))
)
async def test_failed_or_unknown_reconciliation_does_not_record_reply(
    verification: EffectViolation | None,
) -> None:
    snapshot = _snapshot()
    pipeline = _pipeline(receipt=None)
    if verification is not None:
        pipeline._adapter.observe.side_effect = verification

    assert await pipeline._reconcile(snapshot) is True

    pipeline._interaction_delivery.record_party_response.assert_not_awaited()
