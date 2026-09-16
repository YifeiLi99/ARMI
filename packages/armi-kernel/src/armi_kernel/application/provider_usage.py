"""Provider metering values and integer pricing; persistence belongs to callers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from fractions import Fraction


class UsageUnit(StrEnum):
    INPUT_TOKENS = "input_tokens"
    CACHED_INPUT_TOKENS = "cached_input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    AUDIO_MILLISECONDS = "audio_milliseconds"
    TEXT_CHARACTERS = "text_characters"
    WEB_SEARCH_CALLS = "web_search_calls"


class UsageSource(StrEnum):
    PROVIDER = "provider"
    LOCAL_MEASUREMENT = "local_measurement"


class CostStatus(StrEnum):
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    UNPRICED = "unpriced"
    USAGE_UNKNOWN = "usage_unknown"
    NOT_BILLABLE = "not_billable"


@dataclass(frozen=True, slots=True)
class UsageQuantity:
    unit: UsageUnit
    quantity: int
    source: UsageSource = UsageSource.PROVIDER

    def __post_init__(self) -> None:
        if (
            type(self.unit) is not UsageUnit
            or type(self.quantity) is not int
            or self.quantity < 0
            or type(self.source) is not UsageSource
        ):
            raise ValueError("USAGE-QUANTITY")


@dataclass(frozen=True, slots=True)
class UnitPrice:
    unit: UsageUnit
    microyuan: int
    per_quantity: int

    def __post_init__(self) -> None:
        if (
            type(self.unit) is not UsageUnit
            or type(self.microyuan) is not int
            or self.microyuan < 0
            or type(self.per_quantity) is not int
            or self.per_quantity <= 0
        ):
            raise ValueError("USAGE-PRICE")


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    snapshot_id: str
    provider: str
    model: str
    service: str
    effective_from: datetime
    verified_at: datetime
    source_url: str
    rates: tuple[UnitPrice, ...]
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        if (
            any(
                not value.strip()
                for value in (self.snapshot_id, self.provider, self.model, self.service)
            )
            or not self.source_url.startswith("https://")
            or self.effective_from.tzinfo is None
            or self.verified_at.tzinfo is None
            or (
                self.effective_until is not None
                and (
                    self.effective_until.tzinfo is None
                    or self.effective_until <= self.effective_from
                )
            )
            or len({rate.unit for rate in self.rates}) != len(self.rates)
        ):
            raise ValueError("USAGE-PRICE-SNAPSHOT")


@dataclass(frozen=True, slots=True)
class CostComponent:
    unit: UsageUnit
    quantity: int
    source: UsageSource
    price: UnitPrice
    estimated_microyuan: int


@dataclass(frozen=True, slots=True)
class CostEstimate:
    status: CostStatus
    known_microyuan: int | None
    components: tuple[CostComponent, ...]
    missing_usage: tuple[UsageUnit, ...]
    missing_prices: tuple[UsageUnit, ...]
    snapshot_id: str | None
    currency: str = "CNY"
    rounding: str = "ceil_microyuan_per_component"


@dataclass(frozen=True, slots=True)
class PriceCatalog:
    snapshots: tuple[PriceSnapshot, ...]

    def __post_init__(self) -> None:
        if len({item.snapshot_id for item in self.snapshots}) != len(self.snapshots):
            raise ValueError("USAGE-PRICE-DUPLICATE")
        for index, left in enumerate(self.snapshots):
            for right in self.snapshots[index + 1 :]:
                if (left.provider, left.model, left.service) != (
                    right.provider,
                    right.model,
                    right.service,
                ):
                    continue
                if (
                    left.effective_until is None
                    or right.effective_from < left.effective_until
                ) and (
                    right.effective_until is None
                    or left.effective_from < right.effective_until
                ):
                    raise ValueError("USAGE-PRICE-OVERLAP")

    def select(
        self, *, provider: str, model: str, service: str, at: datetime
    ) -> PriceSnapshot | None:
        if at.tzinfo is None:
            raise ValueError("USAGE-TIMEZONE")
        return next(
            (
                item
                for item in self.snapshots
                if (
                    (item.provider, item.model, item.service)
                    == (provider, model, service)
                    and item.effective_from <= at
                    and (item.effective_until is None or at < item.effective_until)
                )
            ),
            None,
        )


def estimate_cost(
    *,
    quantities: tuple[UsageQuantity, ...],
    required_units: tuple[UsageUnit, ...],
    snapshot: PriceSnapshot | None,
    billable: bool = True,
) -> CostEstimate:
    """Price known dimensions without treating missing usage or rates as zero.

    Provider input tokens include cache hits. Ordinary input pricing therefore
    uses input minus cached input. Cache usage remains visible as its own line.
    """
    values = {item.unit: item for item in quantities}
    if len(values) != len(quantities) or len(set(required_units)) != len(
        required_units
    ):
        raise ValueError("USAGE-DUPLICATE-UNIT")
    if not billable:
        return CostEstimate(CostStatus.NOT_BILLABLE, None, (), (), (), None)
    rates = {} if snapshot is None else {item.unit: item for item in snapshot.rates}
    missing_usage = set(required_units) - values.keys()
    missing_prices: set[UsageUnit] = set()
    components: list[CostComponent] = []
    for unit in required_units:
        value = values.get(unit)
        if value is None:
            continue
        quantity = value.quantity
        if unit is UsageUnit.INPUT_TOKENS:
            cached = values.get(UsageUnit.CACHED_INPUT_TOKENS)
            if UsageUnit.CACHED_INPUT_TOKENS in required_units and cached is None:
                continue
            if cached is not None:
                quantity -= cached.quantity
                if quantity < 0:
                    raise ValueError("USAGE-CACHE-EXCEEDS-INPUT")
        rate = rates.get(unit)
        if rate is None:
            # An explicitly reported zero does not require an invented price.
            if quantity != 0:
                missing_prices.add(unit)
            continue
        exact = Fraction(quantity * rate.microyuan, rate.per_quantity)
        rounded = -(-exact.numerator // exact.denominator)
        components.append(CostComponent(unit, quantity, value.source, rate, rounded))
    if not quantities:
        status = CostStatus.USAGE_UNKNOWN
    elif missing_usage or missing_prices:
        status = (
            CostStatus.PARTIAL
            if components
            else (CostStatus.USAGE_UNKNOWN if missing_usage else CostStatus.UNPRICED)
        )
    else:
        status = CostStatus.ESTIMATED
    known = (
        sum(item.estimated_microyuan for item in components)
        if components
        else (0 if status is CostStatus.ESTIMATED else None)
    )
    return CostEstimate(
        status,
        known,
        tuple(components),
        tuple(sorted(missing_usage)),
        tuple(sorted(missing_prices)),
        None if snapshot is None else snapshot.snapshot_id,
    )


__all__ = (
    "CostComponent",
    "CostEstimate",
    "CostStatus",
    "PriceCatalog",
    "PriceSnapshot",
    "UnitPrice",
    "UsageQuantity",
    "UsageSource",
    "UsageUnit",
    "estimate_cost",
)
