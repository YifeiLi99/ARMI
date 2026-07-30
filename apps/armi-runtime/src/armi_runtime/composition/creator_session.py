"""Explicit composition of the process-local Creator session boundary."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from armi_kernel.application import CredentialPurpose

from armi_runtime.interfaces.browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
)

from .configuration import ConfigurationViolation
from .environment import PreparedEnvironment

CREATOR_BEARER_LOCATOR: Final = "creator.bearer"
CREATOR_VERIFY_PURPOSE: Final = "creator.bootstrap.verify"
CREATOR_ISSUE_PURPOSE: Final = "creator.bootstrap.issue"


def compose_browser_sessions(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> BrowserSessionStore:
    """Resolve the long bearer once, retain only its digest, and close the handle."""

    locator = prepared.effective.config.secret_locators.get(CREATOR_BEARER_LOCATOR)
    if locator is None:
        raise BrowserSessionViolation("SEC_CREATOR_BEARER_MISSING", status_code=503)
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose(CREATOR_VERIFY_PURPOSE),
        ) as handle:
            config = prepared.effective.config
            return handle.consume(
                lambda value: BrowserSessionStore(
                    creator_bearer=bytes(value),
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    bootstrap_ttl_seconds=config.creator.bootstrap_ttl_seconds,
                    session_ttl_seconds=config.creator.session_ttl_seconds,
                )
            )
    except ConfigurationViolation:
        raise BrowserSessionViolation(
            "SEC_CREATOR_BEARER_UNAVAILABLE", status_code=503
        ) from None


__all__ = (
    "CREATOR_BEARER_LOCATOR",
    "CREATOR_ISSUE_PURPOSE",
    "CREATOR_VERIFY_PURPOSE",
    "compose_browser_sessions",
)
