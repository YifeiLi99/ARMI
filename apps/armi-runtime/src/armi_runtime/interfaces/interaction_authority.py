"""Two authenticated transports, one Creator authority; no synthetic sessions."""

from __future__ import annotations

from uuid import UUID

from armi_local_control.binding import AuthenticatedDelegate
from starlette.requests import Request

from .browser_sessions import (
    BrowserSessionStore,
    BrowserSessionViolation,
    SessionMetadata,
)


def authenticated_delegate(request: Request) -> AuthenticatedDelegate | None:
    value = request.scope.get("armi.authenticated_delegate")
    return value if isinstance(value, AuthenticatedDelegate) else None


def delegate_id(request: Request) -> UUID | None:
    caller = authenticated_delegate(request)
    return None if caller is None else caller.delegate_id


def verify_interaction(
    request: Request, sessions: BrowserSessionStore | None, token: str | None
) -> SessionMetadata | AuthenticatedDelegate:
    caller = authenticated_delegate(request)
    if caller is not None:
        return caller
    if token is None or sessions is None:
        raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
    return sessions.verify(token)


__all__ = ("authenticated_delegate", "delegate_id", "verify_interaction")
