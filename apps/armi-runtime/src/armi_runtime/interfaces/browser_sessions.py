"""Process-local Creator bootstrap and browser-session security state."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

_CREATOR_BEARER = re.compile(r"^creator-v1\.[A-Za-z0-9_-]{43}$", re.ASCII)
_BOOTSTRAP_CODE = re.compile(r"^bootstrap-v1\.[A-Za-z0-9_-]{22}$", re.ASCII)
_SESSION_BEARER = re.compile(r"^browser-v1\.[A-Za-z0-9_-]{43}$", re.ASCII)
_FAILURE_LIMIT: Final = 5
_FAILURE_WINDOW_SECONDS: Final = 60.0


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
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedBootstrap:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EstablishedSession:
    token: str
    metadata: SessionMetadata


@dataclass(frozen=True, slots=True)
class _StoredBootstrap:
    digest: bytes
    expires_monotonic: float
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _StoredSession:
    digest: bytes
    metadata: SessionMetadata
    expires_monotonic: float


def _token(prefix: str, byte_count: int) -> str:
    encoded = base64.urlsafe_b64encode(secrets.token_bytes(byte_count))
    return f"{prefix}.{encoded.rstrip(b'=').decode('ascii')}"


def _digest(domain: bytes, value: str) -> bytes:
    return hashlib.sha256(domain + b"\0" + value.encode("ascii")).digest()


class BrowserSessionStore:
    """Own the single bootstrap code and browser session for one Runtime."""

    __slots__ = (
        "_bootstrap",
        "_bootstrap_failures",
        "_bootstrap_ttl",
        "_creator_digest",
        "_creator_failures",
        "_creator_party_id",
        "_environment_id",
        "_lock",
        "_monotonic",
        "_now",
        "_session",
        "_session_failures",
        "_session_ttl",
    )

    def __init__(
        self,
        *,
        creator_bearer: bytes,
        environment_id: UUID,
        creator_party_id: UUID,
        bootstrap_ttl_seconds: int,
        session_ttl_seconds: int,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            bearer = creator_bearer.decode("ascii")
        except UnicodeDecodeError:
            raise BrowserSessionViolation(
                "SEC_CREATOR_BEARER_FORMAT", status_code=503
            ) from None
        if _CREATOR_BEARER.fullmatch(bearer) is None:
            raise BrowserSessionViolation("SEC_CREATOR_BEARER_FORMAT", status_code=503)
        if (
            environment_id.version != 7
            or creator_party_id.version != 7
            or bootstrap_ttl_seconds <= 0
            or session_ttl_seconds <= 0
        ):
            raise BrowserSessionViolation("SEC_CREATOR_CONFIGURATION", status_code=503)
        self._creator_digest = _digest(b"armi.creator-bearer.v1", bearer)
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id
        self._bootstrap_ttl = bootstrap_ttl_seconds
        self._session_ttl = session_ttl_seconds
        self._monotonic = monotonic
        self._now = now if now is not None else lambda: datetime.now(UTC)
        self._bootstrap: _StoredBootstrap | None = None
        self._session: _StoredSession | None = None
        self._creator_failures: deque[float] = deque()
        self._bootstrap_failures: deque[float] = deque()
        self._session_failures: deque[float] = deque()
        self._lock = threading.Lock()

    def _check_rate(self, failures: deque[float]) -> None:
        current = self._monotonic()
        while failures and current - failures[0] >= _FAILURE_WINDOW_SECONDS:
            failures.popleft()
        if len(failures) >= _FAILURE_LIMIT:
            raise BrowserSessionViolation("AUTH_RATE_LIMITED", status_code=429)

    def _reject(self, failures: deque[float], code: str) -> None:
        failures.append(self._monotonic())
        raise BrowserSessionViolation(code)

    def issue(self, creator_bearer: str) -> IssuedBootstrap:
        with self._lock:
            self._check_rate(self._creator_failures)
            if _CREATOR_BEARER.fullmatch(
                creator_bearer
            ) is None or not hmac.compare_digest(
                _digest(b"armi.creator-bearer.v1", creator_bearer),
                self._creator_digest,
            ):
                self._reject(self._creator_failures, "AUTH_CREATOR_REJECTED")
            code = _token("bootstrap-v1", 16)
            issued_at = self._now()
            expires_at = issued_at + timedelta(seconds=self._bootstrap_ttl)
            self._bootstrap = _StoredBootstrap(
                _digest(b"armi.bootstrap-code.v1", code),
                self._monotonic() + self._bootstrap_ttl,
                expires_at,
            )
            return IssuedBootstrap(code, expires_at)

    def exchange(self, code: str) -> EstablishedSession:
        with self._lock:
            self._check_rate(self._bootstrap_failures)
            stored = self._bootstrap
            valid = (
                stored is not None
                and self._monotonic() < stored.expires_monotonic
                and _BOOTSTRAP_CODE.fullmatch(code) is not None
                and hmac.compare_digest(
                    _digest(b"armi.bootstrap-code.v1", code),
                    stored.digest,
                )
            )
            if not valid:
                self._reject(self._bootstrap_failures, "AUTH_BOOTSTRAP_REJECTED")
            self._bootstrap = None
            token = _token("browser-v1", 32)
            issued_at = self._now()
            metadata = SessionMetadata(
                self._environment_id,
                self._creator_party_id,
                issued_at,
                issued_at + timedelta(seconds=self._session_ttl),
            )
            self._session = _StoredSession(
                _digest(b"armi.browser-session.v1", token),
                metadata,
                self._monotonic() + self._session_ttl,
            )
            return EstablishedSession(token, metadata)

    def verify(self, token: str) -> SessionMetadata:
        with self._lock:
            self._check_rate(self._session_failures)
            stored = self._session
            valid = (
                stored is not None
                and self._monotonic() < stored.expires_monotonic
                and _SESSION_BEARER.fullmatch(token) is not None
                and hmac.compare_digest(
                    _digest(b"armi.browser-session.v1", token),
                    stored.digest,
                )
            )
            if not valid:
                if stored is not None and self._monotonic() >= stored.expires_monotonic:
                    self._session = None
                self._reject(self._session_failures, "AUTH_SESSION_REQUIRED")
            assert stored is not None
            return stored.metadata

    def revoke(self, token: str) -> None:
        with self._lock:
            self._check_rate(self._session_failures)
            stored = self._session
            if (
                stored is None
                or _SESSION_BEARER.fullmatch(token) is None
                or not hmac.compare_digest(
                    _digest(b"armi.browser-session.v1", token),
                    stored.digest,
                )
            ):
                self._reject(self._session_failures, "AUTH_SESSION_REQUIRED")
            self._session = None

    def revoke_all(self) -> None:
        with self._lock:
            self._bootstrap = None
            self._session = None
            self._creator_failures.clear()
            self._bootstrap_failures.clear()
            self._session_failures.clear()


__all__ = (
    "BrowserSessionStore",
    "BrowserSessionViolation",
    "EstablishedSession",
    "IssuedBootstrap",
    "SessionMetadata",
)
