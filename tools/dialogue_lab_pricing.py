"""Native-currency lab estimates; never fabricate FX or replace durable receipts."""

from decimal import Decimal
from typing import Literal

from armi_kernel import load_yaml_file
from pydantic import BaseModel, ConfigDict, Field

from tools.dialogue_lab_support import ROOT


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    service: str
    currency: Literal["USD"]
    verified_at: str
    source_url: str
    per_million: dict[Literal["input_tokens", "output_tokens"], Decimal]


class Prices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_kind: Literal["armi.dialogue-lab-pricing"]
    prices: list[ModelPrice] = Field(min_length=1)


def estimate_calls(calls: list[dict]) -> dict:
    prices = Prices.model_validate(
        load_yaml_file(ROOT / "configs/dialogue-lab-pricing.yaml")
    )
    totals: dict[str, Decimal] = {}
    estimates = []
    unknown = []
    non_billable = []
    for call in calls:
        receipt = call["receipt"]
        call_id = receipt["call_id"]
        cost = receipt["cost"]
        if cost["status"] == "not_billable":
            non_billable.append(call_id)
            continue
        if cost["status"] == "estimated":
            currency = cost["currency"]
            amount = Decimal(cost["known_microyuan"]) / 1_000_000
            source = receipt["price"]
        else:
            price = next(
                (
                    item
                    for item in prices.prices
                    if (item.provider, item.model, item.service)
                    == (receipt["provider"], receipt["model"], receipt["service"])
                ),
                None,
            )
            quantities = {
                item["unit"]: item["quantity"] for item in receipt["quantities"]
            }
            if price is None or not price.per_million.keys() <= quantities.keys():
                unknown.append(call_id)
                continue
            currency = price.currency
            amount = sum(
                (
                    Decimal(quantities[unit]) * rate / 1_000_000
                    for unit, rate in price.per_million.items()
                ),
                Decimal(0),
            )
            source = price.model_dump(mode="json")
        if receipt["outcome"] in {"pending", "unknown"}:
            unknown.append(call_id)
        totals[currency] = totals.get(currency, Decimal(0)) + amount
        estimates.append(
            {
                "call_id": call_id,
                "currency": currency,
                "amount": str(amount),
                "price_source": source,
            }
        )
    return {
        "label": "official_list_price_estimate_not_account_bill",
        "known_totals": {currency: str(value) for currency, value in totals.items()},
        "unknown_call_ids": unknown,
        "non_billable_call_ids": non_billable,
        "calls": estimates,
    }
