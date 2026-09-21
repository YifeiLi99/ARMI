"""Shared response shapes for Creator and Admin usage queries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class UsageTotals(UsageResponse):
    billable_calls: int
    auxiliary_requests: int
    known_microyuan: int | None
    incomplete_calls: int
    usage_unconfirmed_calls: int
    unpriced_calls: int


class UsageDay(UsageResponse):
    date: str
    totals: UsageTotals
    units: dict[str, int]


class UsageGroup(UsageResponse):
    service: str
    model: str
    totals: UsageTotals
    units: dict[str, int]


class UsageSummary(UsageResponse):
    currency: Literal["CNY"]
    price_label: Literal["official_list_price_estimate"]
    timezone: Literal["Asia/Shanghai"]
    coverage: str
    totals: UsageTotals
    units: dict[str, int]
    daily: list[UsageDay]
    groups: list[UsageGroup]


class UsageCall(UsageResponse):
    owner: str
    attempt_id: str
    operation_id: str | None
    reference_kind: str
    reference_id: str
    business_result: str | None
    receipt: UsageReceipt
    auxiliary_requests: list[UsageReceipt] = Field(
        default_factory=lambda: list[UsageReceipt]()
    )


class UsageCalls(UsageResponse):
    total: int
    items: list[UsageCall]


class UsageQuantityResponse(UsageResponse):
    unit: str
    quantity: int
    source: str


class UsageRate(UsageResponse):
    unit: str
    microyuan: int
    per_quantity: int


class UsagePrice(UsageResponse):
    snapshot_id: str
    provider: str
    model: str
    service: str
    effective_from: str
    effective_until: str | None
    verified_at: str
    source_url: str
    rates: list[UsageRate]


class UsageCostComponent(UsageQuantityResponse):
    price: UsageRate
    estimated_microyuan: int


class UsageCost(UsageResponse):
    status: str
    known_microyuan: int | None
    components: list[UsageCostComponent]
    missing_usage: list[str]
    missing_prices: list[str]
    snapshot_id: str | None
    currency: str
    rounding: str


class UsageReceipt(UsageResponse):
    schema_version: str
    call_id: str
    provider: str
    model: str
    service: str
    purpose: str
    started_at: str
    finished_at: str | None
    billable: bool
    outcome: str
    provider_request_id: str | None
    response_model: str | None
    quantities: list[UsageQuantityResponse]
    cost: UsageCost
    price: UsagePrice | None
    raw_usage: dict[str, JsonValue] | None
    error_code: str | None
    parent_call_id: str | None = None
    received_at: str | None = None


UsageCall.model_rebuild()
UsageCalls.model_rebuild()
