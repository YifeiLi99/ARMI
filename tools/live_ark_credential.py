"""Load the paid-live Ark credential from the configured ARMI environment."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid7

from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    load_price_catalog,
    provider_meter_scope,
)
from armi_local_control import ProviderCheckReceipts
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.environment import prepare_environment

_LOCATOR_NAME = "model.ark_api_key"
_PURPOSE = CredentialPurpose("model.request")


@dataclass(slots=True)
class LiveProviderMeter:
    prices: PriceCatalog
    receipts: dict[str, ProviderCallReceipt]

    def report(self) -> dict[str, object]:
        return {"provider_calls": [item.document() for item in self.receipts.values()]}


@contextmanager
def live_provider_meter(environment_root: Path) -> Generator[LiveProviderMeter]:
    journal = ProviderCheckReceipts(environment_root)
    identity = str(uuid7())
    prices = load_price_catalog(
        runtime_config_path("provider-pricing.yaml", environment_root=environment_root)
    )
    meter = LiveProviderMeter(prices, {})

    async def save(receipt: ProviderCallReceipt) -> None:
        journal.save(
            verification_id=identity,
            credential_name=_LOCATOR_NAME,
            call=receipt.document(),
        )
        meter.receipts[receipt.call_id] = receipt

    try:
        with provider_meter_scope(
            ProviderMeterScope(save, prices, "explicit_live_verification")
        ):
            yield meter
    finally:
        journal.settle_interrupted(identity)


@dataclass(frozen=True, slots=True)
class LiveArkCredential:
    port: CredentialPort
    locator: CredentialLocator

    def read_text(self) -> str:
        with self.port.resolve(self.locator, _PURPOSE) as handle:
            value = handle.consume(
                lambda secret: bytes(secret).decode("utf-8", errors="strict")
            )
        if not value or value != value.strip():
            raise ValueError("live Ark credential is invalid")
        return value


def load_live_ark_credential(environment_root: Path) -> LiveArkCredential:
    prepared = prepare_environment(
        environment_root,
        credential_scope={_PURPOSE.value: _LOCATOR_NAME},
    )
    locator = prepared.effective.config.secret_locators.get(_LOCATOR_NAME)
    if locator is None:
        raise ValueError("live Ark credential is unavailable")
    return LiveArkCredential(prepared.credential_port, locator)


__all__ = (
    "LiveArkCredential",
    "load_live_ark_credential",
)
