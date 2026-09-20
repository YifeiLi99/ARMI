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
from armi_runtime.composition.model_verification import (
    load_active_binding as load_active_model_binding,
)

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
            credential_name={
                "volcengine_ark": _LOCATOR_NAME,
                "qwen": "model.qwen_api_key",
                "deepseek": "model.deepseek_api_key",
            }[receipt.provider],
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
    purpose: CredentialPurpose = _PURPOSE

    def read_text(self) -> str:
        with self.port.resolve(self.locator, self.purpose) as handle:
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


def load_live_text_credential(environment_root: Path) -> LiveArkCredential:
    binding = load_active_model_binding(
        runtime_config_path("model-bindings.yaml", environment_root=environment_root)
    )
    name = f"model.{binding.provider}_api_key"
    purpose = CredentialPurpose(f"model.request.{binding.provider}")
    prepared = prepare_environment(
        environment_root, credential_scope={purpose.value: name}
    )
    locator = prepared.effective.config.secret_locators.get(name)
    if locator is None:
        raise ValueError("live text credential is unavailable")
    return LiveArkCredential(prepared.credential_port, locator, purpose)


__all__ = (
    "LiveArkCredential",
    "load_live_ark_credential",
    "load_live_text_credential",
)
