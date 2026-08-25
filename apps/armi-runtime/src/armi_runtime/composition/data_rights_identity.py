"""Process-local Data Rights identity token derivation."""

from __future__ import annotations

import hashlib
import hmac
from typing import Final

from armi_kernel.application import CredentialPurpose

from armi_runtime.composition.configuration import ConfigurationViolation
from armi_runtime.composition.environment import PreparedEnvironment
from armi_runtime.composition.runtime_errors import RuntimeViolation

IDENTITY_TOKEN_LOCATOR: Final = "data_rights.identity_token_key"
IDENTITY_TOKEN_PURPOSE: Final = "data_rights.identity_token"
_KEY_DOMAIN: Final = b"armi.data-rights.identity-key.v1\x00"
_TOKEN_DOMAIN: Final = b"armi.data-rights.identity-token.v1\x00"


class DataRightsIdentityTokenKey:
    __slots__ = ("_key", "_key_identity")

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise RuntimeViolation(
                "SEC-DATA-RIGHTS-IDENTITY-KEY-LENGTH",
                "data rights identity token key must contain at least 32 bytes",
            )
        self._key = key
        self._key_identity = "sha256:" + hashlib.sha256(_KEY_DOMAIN + key).hexdigest()

    @property
    def key_identity(self) -> str:
        return self._key_identity

    def token(self, *, domain: str, value: str) -> str:
        domain_bytes = domain.encode("utf-8")
        value_bytes = value.encode("utf-8")
        payload = (
            _TOKEN_DOMAIN
            + len(domain_bytes).to_bytes(4, "big")
            + domain_bytes
            + len(value_bytes).to_bytes(4, "big")
            + value_bytes
        )
        return (
            "hmac-sha256:v1:" + hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        )


def derive_data_rights_identity_token_key(
    prepared: PreparedEnvironment,
) -> DataRightsIdentityTokenKey:
    locator = prepared.effective.config.secret_locators.get(IDENTITY_TOKEN_LOCATOR)
    if locator is None:
        raise RuntimeViolation(
            "SEC-DATA-RIGHTS-IDENTITY-KEY-MISSING",
            "data rights identity token key locator is required",
        )
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose(IDENTITY_TOKEN_PURPOSE)
        ) as handle:
            return handle.consume(
                lambda value: DataRightsIdentityTokenKey(bytes(value))
            )
    except ConfigurationViolation:
        raise RuntimeViolation(
            "SEC-DATA-RIGHTS-IDENTITY-KEY-UNAVAILABLE",
            "data rights identity token key is unavailable",
        ) from None


__all__ = (
    "IDENTITY_TOKEN_LOCATOR",
    "IDENTITY_TOKEN_PURPOSE",
    "DataRightsIdentityTokenKey",
    "derive_data_rights_identity_token_key",
)
