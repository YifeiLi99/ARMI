"""Explicit composition of the process-local Creator session boundary."""

from __future__ import annotations

import hashlib
import hmac
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
CREATOR_CURSOR_PURPOSE: Final = "creator.timeline.cursor"
_CURSOR_DOMAIN: Final = b"armi.creator.scene-timeline.cursor-key.v1"


def compose_browser_sessions(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    default_scene_key: str,
) -> BrowserSessionStore:
    """Create the process-local connection store for the same-origin UI."""

    config = prepared.effective.config
    return BrowserSessionStore(
        environment_id=config.environment.environment_id,
        creator_party_id=creator_party_id,
        default_scene_key=default_scene_key,
        session_ttl_seconds=config.creator.session_ttl_seconds,
    )


def derive_timeline_cursor_key(prepared: PreparedEnvironment) -> bytes:
    """Derive a process-local cursor key without retaining the Creator bearer."""

    locator = prepared.effective.config.secret_locators.get(CREATOR_BEARER_LOCATOR)
    if locator is None:
        raise BrowserSessionViolation("SEC_CREATOR_BEARER_MISSING", status_code=503)
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose(CREATOR_CURSOR_PURPOSE),
        ) as handle:
            return handle.consume(
                lambda value: hmac.new(
                    bytes(value),
                    _CURSOR_DOMAIN,
                    hashlib.sha256,
                ).digest()
            )
    except ConfigurationViolation:
        raise BrowserSessionViolation(
            "SEC_CREATOR_BEARER_UNAVAILABLE", status_code=503
        ) from None


__all__ = (
    "CREATOR_BEARER_LOCATOR",
    "CREATOR_CURSOR_PURPOSE",
    "CREATOR_VERIFY_PURPOSE",
    "compose_browser_sessions",
    "derive_timeline_cursor_key",
)
