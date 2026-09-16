import asyncio
from datetime import UTC, datetime

import pytest
from armi_kernel.application import (
    CostStatus,
    PriceCatalog,
    PriceSnapshot,
    ProviderMeterScope,
    UnitPrice,
    UsageUnit,
    provider_call,
    provider_meter_scope,
)


@pytest.mark.asyncio
async def test_no_sink_means_no_network_dispatch():
    dispatched = False
    with pytest.raises(RuntimeError, match="USAGE-DURABLE-SINK-REQUIRED"):
        async with provider_call(provider="p", model="m", service="generation"):
            dispatched = True
    assert not dispatched


@pytest.mark.asyncio
async def test_failed_registration_means_no_network_dispatch():
    dispatched = False

    async def fail(_receipt):
        raise OSError("storage unavailable")

    with (
        provider_meter_scope(ProviderMeterScope(fail, PriceCatalog(()), "test")),
        pytest.raises(OSError),
    ):
        async with provider_call(provider="p", model="m", service="generation"):
            dispatched = True
    assert not dispatched


@pytest.mark.asyncio
async def test_usage_survives_business_failure_and_is_not_added_twice():
    rows = []

    async def save(receipt):
        rows.append(receipt)

    with (
        provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")),
        pytest.raises(ValueError, match="invalid business output"),
    ):
        async with provider_call(provider="p", model="m", service="generation") as call:
            assert len(rows) == 1
            await call.capture(
                usage={
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cached_input_tokens": 0,
                },
                provider_request_id="r",
            )
            await call.capture(usage={"output_tokens": 20})
            raise ValueError("invalid business output")
    final = rows[-1]
    assert final.outcome == "unknown"
    assert final.provider_request_id == "r"
    assert {item.unit: item.quantity for item in final.quantities} == {
        UsageUnit.INPUT_TOKENS: 100,
        UsageUnit.OUTPUT_TOKENS: 20,
        UsageUnit.CACHED_INPUT_TOKENS: 0,
    }
    assert final.cost.status is CostStatus.UNPRICED
    assert final.cost.known_microyuan is None


@pytest.mark.asyncio
async def test_cancellation_keeps_pending_call_and_does_not_replay():
    rows = []

    async def save(receipt):
        rows.append(receipt)

    with (
        provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")),
        pytest.raises(asyncio.CancelledError),
    ):
        async with provider_call(provider="p", model="m", service="generation"):
            raise asyncio.CancelledError
    assert len({row.call_id for row in rows}) == 1
    assert rows[-1].outcome == "unknown"
    assert rows[-1].cost.status is CostStatus.USAGE_UNKNOWN


@pytest.mark.asyncio
async def test_auxiliary_request_is_traced_without_fabricating_a_zero_bill():
    rows = []

    async def save(receipt):
        rows.append(receipt)

    with provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")):
        async with provider_call(
            provider="p", model="m", service="tokenization"
        ) as call:
            await call.capture(usage={"input_tokens": 100, "unsafe": "secret-body"})
    assert rows[-1].outcome == "returned"
    assert rows[-1].cost.status is CostStatus.NOT_BILLABLE
    assert rows[-1].raw_usage == {"input_tokens": 100}


@pytest.mark.asyncio
async def test_invalid_supplier_usage_is_saved_before_validation_failure():
    rows = []

    async def save(receipt):
        rows.append(receipt)

    with (
        provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "test")),
        pytest.raises(ValueError, match="USAGE-CACHE-EXCEEDS-INPUT"),
    ):
        async with provider_call(provider="p", model="m", service="generation") as call:
            await call.capture(
                usage={"input_tokens": 2, "cached_input_tokens": 3, "output_tokens": 1},
                provider_request_id="invalid-usage-response",
            )
    assert rows[-1].raw_usage["cached_input_tokens"] == 3
    assert rows[-1].provider_request_id == "invalid-usage-response"
    assert rows[-1].error_code == "USAGE-INVALID-QUANTITIES"
    assert rows[-1].cost.known_microyuan is None


@pytest.mark.asyncio
async def test_inflight_price_is_frozen_even_if_another_scope_changes_prices():
    rows = []

    async def save(receipt):
        rows.append(receipt)

    def catalog(amount):
        return PriceCatalog(
            (
                PriceSnapshot(
                    str(amount),
                    "p",
                    "resource",
                    "tts",
                    datetime(2020, 1, 1, tzinfo=UTC),
                    datetime(2020, 1, 1, tzinfo=UTC),
                    "https://example.test/price",
                    (UnitPrice(UsageUnit.TEXT_CHARACTERS, amount, 10000),),
                ),
            )
        )

    from armi_kernel.application import UsageQuantity

    with provider_meter_scope(ProviderMeterScope(save, catalog(3_000_000), "tts")):
        async with provider_call(provider="p", model="resource", service="tts") as call:
            with provider_meter_scope(
                ProviderMeterScope(save, catalog(9_000_000), "tts")
            ):
                await call.capture(
                    usage={"text_words": 10},
                    quantities=(UsageQuantity(UsageUnit.TEXT_CHARACTERS, 10),),
                )
    assert rows[-1].cost.known_microyuan == 3000
    assert rows[-1].price.snapshot_id == "3000000"
