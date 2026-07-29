"""Command-local credential purpose and locator authorization."""

from __future__ import annotations

from collections.abc import Mapping

from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    SecretHandle,
)

from .configuration import ConfigurationViolation


class ScopedCredentialPort(CredentialPort):
    """Permit only exact locator identities for exact command purposes."""

    __slots__ = ("_allowed", "_delegate")

    def __init__(
        self,
        delegate: CredentialPort,
        *,
        allowed: Mapping[str, CredentialLocator],
    ) -> None:
        self._delegate = delegate
        self._allowed = dict(allowed)

    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        if self._allowed.get(purpose.value) != locator:
            raise ConfigurationViolation(
                "SEC-SECRET-PURPOSE",
                "credential locator is not approved for this command purpose",
            )
        return self._delegate.resolve(locator, purpose)


__all__ = ("ScopedCredentialPort",)
