"""Browser authentication for Creator HTTP requests."""

from __future__ import annotations

from starlette.requests import Request

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)


def verify_interaction(
    request: Request, sessions: BrowserSessionStore | None, token: str | None
) -> SessionMetadata:
    if token is None or sessions is None:
        raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
    return sessions.verify(token)


__all__ = ("verify_interaction",)
