from datetime import UTC, datetime

import pytest
from armi_kernel.application import (
    CostStatus,
    PriceCatalog,
    PriceSnapshot,
    UnitPrice,
    UsageQuantity,
    UsageUnit,
    estimate_cost,
)

AT = datetime(2026, 9, 16, tzinfo=UTC)
TOKEN_UNITS = (
    UsageUnit.INPUT_TOKENS,
    UsageUnit.CACHED_INPUT_TOKENS,
    UsageUnit.OUTPUT_TOKENS,
)


def price(*rates: UnitPrice) -> PriceSnapshot:
    return PriceSnapshot(
        "test-price",
        "test-provider",
        "test-model",
        "generation",
        AT,
        AT,
        "https://example.test/pricing",
        rates,
    )


def test_cache_hits_are_subtracted_from_regular_input():
    result = estimate_cost(
        quantities=tuple(
            UsageQuantity(unit, count)
            for unit, count in zip(TOKEN_UNITS, (1000, 400, 100), strict=True)
        ),
        required_units=TOKEN_UNITS,
        snapshot=price(
            UnitPrice(UsageUnit.INPUT_TOKENS, 6_000_000, 1_000_000),
            UnitPrice(UsageUnit.CACHED_INPUT_TOKENS, 1_000_000, 1_000_000),
            UnitPrice(UsageUnit.OUTPUT_TOKENS, 30_000_000, 1_000_000),
        ),
    )
    assert result.status is CostStatus.ESTIMATED
    assert result.known_microyuan == 7000
    assert result.components[0].quantity == 600


def test_missing_usage_does_not_become_zero_cost():
    result = estimate_cost(quantities=(), required_units=TOKEN_UNITS, snapshot=None)
    assert result.status is CostStatus.USAGE_UNKNOWN
    assert result.known_microyuan is None


def test_missing_search_price_preserves_known_model_subtotal():
    result = estimate_cost(
        quantities=(
            UsageQuantity(UsageUnit.OUTPUT_TOKENS, 100),
            UsageQuantity(UsageUnit.WEB_SEARCH_CALLS, 2),
        ),
        required_units=(UsageUnit.OUTPUT_TOKENS, UsageUnit.WEB_SEARCH_CALLS),
        snapshot=price(UnitPrice(UsageUnit.OUTPUT_TOKENS, 30_000_000, 1_000_000)),
    )
    assert result.status is CostStatus.PARTIAL
    assert result.known_microyuan == 3000
    assert result.missing_prices == (UsageUnit.WEB_SEARCH_CALLS,)


def test_missing_cached_usage_does_not_charge_all_input_at_regular_price():
    result = estimate_cost(
        quantities=(UsageQuantity(UsageUnit.INPUT_TOKENS, 1000),),
        required_units=TOKEN_UNITS,
        snapshot=price(UnitPrice(UsageUnit.INPUT_TOKENS, 6_000_000, 1_000_000)),
    )
    assert result.known_microyuan is None
    assert UsageUnit.CACHED_INPUT_TOKENS in result.missing_usage


def test_sub_microyuan_rounding_is_exact_and_has_no_budget_ceiling():
    for count, expected in ((1, 1), (3_600_000, 1_000_001)):
        result = estimate_cost(
            quantities=(UsageQuantity(UsageUnit.AUDIO_MILLISECONDS, count),),
            required_units=(UsageUnit.AUDIO_MILLISECONDS,),
            snapshot=price(
                UnitPrice(UsageUnit.AUDIO_MILLISECONDS, 1_000_001, 3_600_000)
            ),
        )
        assert result.known_microyuan == expected


def test_explicit_zero_usage_and_non_billable_are_distinct():
    zero = estimate_cost(
        quantities=(UsageQuantity(UsageUnit.OUTPUT_TOKENS, 0),),
        required_units=(UsageUnit.OUTPUT_TOKENS,),
        snapshot=None,
    )
    assert zero.status is CostStatus.ESTIMATED
    assert zero.known_microyuan == 0
    free = estimate_cost(
        quantities=(), required_units=(), snapshot=None, billable=False
    )
    assert free.status is CostStatus.NOT_BILLABLE
    assert free.known_microyuan is None


def test_prices_match_exact_model_and_time_without_fallback():
    catalog = PriceCatalog((price(),))
    assert (
        catalog.select(
            provider="test-provider", model="other", service="generation", at=AT
        )
        is None
    )
    assert (
        catalog.select(
            provider="test-provider", model="test-model", service="generation", at=AT
        )
        == price()
    )
    with pytest.raises(ValueError, match="USAGE-PRICE-DUPLICATE"):
        PriceCatalog((price(), price()))


@pytest.mark.parametrize("quantity", [-1, True, 1.5])
def test_invalid_quantities_are_rejected(quantity):
    with pytest.raises(ValueError, match="USAGE-QUANTITY"):
        UsageQuantity(UsageUnit.INPUT_TOKENS, quantity)
