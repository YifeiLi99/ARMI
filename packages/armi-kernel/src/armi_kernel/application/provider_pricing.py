"""Strict loader for the single versioned provider price configuration."""

from datetime import datetime
from pathlib import Path
from typing import cast

from armi_kernel import load_yaml_file

from .provider_usage import PriceCatalog, PriceSnapshot, UnitPrice, UsageUnit


def _mapping(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(cast(dict[object, object], value)) != fields:
        raise ValueError("USAGE-PRICING-CONFIG")
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("USAGE-PRICING-CONFIG")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("USAGE-PRICING-CONFIG")
    return value


def load_price_catalog(path: Path) -> PriceCatalog:
    document = _mapping(
        load_yaml_file(path), {"schema_version", "currency", "snapshots"}
    )
    if (
        document["schema_version"] != "armi.provider-pricing.v1"
        or document["currency"] != "CNY"
    ):
        raise ValueError("USAGE-PRICING-CONFIG")
    items = document["snapshots"]
    if type(items) is not list:
        raise ValueError("USAGE-PRICING-CONFIG")
    snapshots: list[PriceSnapshot] = []
    for value in cast(list[object], items):
        item = _mapping(
            value,
            {
                "snapshot_id",
                "provider",
                "model",
                "service",
                "effective_from",
                "effective_until",
                "verified_at",
                "source_url",
                "rates",
            },
        )
        rate_values = item["rates"]
        if type(rate_values) is not list:
            raise ValueError("USAGE-PRICING-CONFIG")
        rates: list[UnitPrice] = []
        for rate_value in cast(list[object], rate_values):
            rate = _mapping(rate_value, {"unit", "microyuan", "per_quantity"})
            rates.append(
                UnitPrice(
                    UsageUnit(_text(rate["unit"])),
                    _integer(rate["microyuan"]),
                    _integer(rate["per_quantity"]),
                )
            )
        snapshots.append(
            PriceSnapshot(
                _text(item["snapshot_id"]),
                _text(item["provider"]),
                _text(item["model"]),
                _text(item["service"]),
                datetime.fromisoformat(_text(item["effective_from"])),
                datetime.fromisoformat(_text(item["verified_at"])),
                _text(item["source_url"]),
                tuple(rates),
                None
                if item["effective_until"] is None
                else datetime.fromisoformat(_text(item["effective_until"])),
            )
        )
    return PriceCatalog(tuple(snapshots))


__all__ = ("load_price_catalog",)
