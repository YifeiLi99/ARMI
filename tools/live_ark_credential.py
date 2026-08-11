"""Load the paid-live Ark credential from the configured ARMI environment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from armi_kernel.application import CredentialLocator, CredentialPort, CredentialPurpose
from armi_runtime.composition.environment import prepare_environment

DEFAULT_ENVIRONMENT_ROOT = Path(__file__).resolve().parents[2] / "ARMI-Environment"
_LOCATOR_NAME = "model.ark_api_key"
_PURPOSE = CredentialPurpose("model.request")


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
    "DEFAULT_ENVIRONMENT_ROOT",
    "LiveArkCredential",
    "load_live_ark_credential",
)
