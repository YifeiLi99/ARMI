"""Process-local connection state for the same-origin Creator UI."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

_SESSION_BEARER = re.compile(r"^browser-v1\.[A-Za-z0-9_-]{43}$", re.ASCII)


class BrowserSessionViolation(RuntimeError):
    """A stable, secret-free browser-session failure."""

    def __init__(self, code: str, *, status_code: int = 401) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    environment_id: UUID
    creator_party_id: UUID
    default_scene_key: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EstablishedSession:
    token: str
    metadata: SessionMetadata


@dataclass(frozen=True, slots=True)
class _StoredSession:
    token: str
    digest: bytes
    metadata: SessionMetadata
    expires_monotonic: float


def _token(prefix: str, byte_count: int) -> str:
    encoded = base64.urlsafe_b64encode(secrets.token_bytes(byte_count))
    return f"{prefix}.{encoded.rstrip(b'=').decode('ascii')}"


def _digest(domain: bytes, value: str) -> bytes:
    return hashlib.sha256(domain + b"\0" + value.encode("ascii")).digest()


class BrowserSessionStore:
    """Own the current same-origin UI connection for one Runtime process."""

    __slots__ = (
        "_creator_party_id",
        "_default_scene_key",
        "_environment_id",
        "_lock",
        "_monotonic",
        "_now",
        "_session",
        "_session_ttl",
    )

    def __init__(
        self,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        session_ttl_seconds: int,
        default_scene_key: str = "default",
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id
        self._default_scene_key = default_scene_key
        self._session_ttl = session_ttl_seconds
        self._monotonic = monotonic
        self._now = now if now is not None else lambda: datetime.now(UTC)
        self._session: _StoredSession | None = None
        self._lock = threading.Lock()

    def establish(self) -> EstablishedSession:
        with self._lock:
            if (
                self._session is not None
                and self._monotonic() < self._session.expires_monotonic
            ):
                return EstablishedSession(
                    self._session.token,
                    self._session.metadata,
                )
            token = _token("browser-v1", 32)
            issued_at = self._now()
            metadata = SessionMetadata(
                self._environment_id,
                self._creator_party_id,
                self._default_scene_key,
                issued_at,
                issued_at + timedelta(seconds=self._session_ttl),
            )
            self._session = _StoredSession(
                token,
                _digest(b"armi.browser-session.v1", token),
                metadata,
                self._monotonic() + self._session_ttl,
            )
            return EstablishedSession(token, metadata)

    def verify(self, token: str) -> SessionMetadata:
        with self._lock:
            stored = self._session
            valid = (
                stored is not None
                and self._monotonic() < stored.expires_monotonic
                and _SESSION_BEARER.fullmatch(token) is not None
                and secrets.compare_digest(
                    _digest(b"armi.browser-session.v1", token), stored.digest
                )
            )
            if not valid:
                if stored is not None and self._monotonic() >= stored.expires_monotonic:
                    self._session = None
                raise BrowserSessionViolation("AUTH_SESSION_REQUIRED")
            return cast(_StoredSession, stored).metadata

    def revoke_all(self) -> None:
        with self._lock:
            self._session = None


__all__ = (
    "BrowserSessionStore",
    "BrowserSessionViolation",
    "EstablishedSession",
    "SessionMetadata",
)
