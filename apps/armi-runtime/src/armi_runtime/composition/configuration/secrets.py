"""The v1 environment and file credential adapters."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Never, TypeVar

from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    SecretHandle,
)

from .errors import ConfigurationViolation
from .paths import has_reparse_point, require_within_roots

_SECRET_ENV_NAME = re.compile(r"^ARMI_SECRET_[A-Z][A-Z0-9_]{0,63}$", re.ASCII)
_ResultT = TypeVar("_ResultT")


class _EphemeralSecretHandle(SecretHandle):
    __slots__ = ("_buffer", "_closed")

    def __init__(self, value: bytes) -> None:
        self._buffer = bytearray(value)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def consume(self, operation: Callable[[memoryview], _ResultT]) -> _ResultT:
        if self._closed:
            raise ConfigurationViolation(
                "SEC-SECRET-CLOSED", "secret handle is already closed"
            )
        view = memoryview(self._buffer).toreadonly()
        try:
            return operation(view)
        finally:
            view.release()

    def close(self) -> None:
        if not self._closed:
            for index in range(len(self._buffer)):
                self._buffer[index] = 0
            self._closed = True

    def __enter__(self) -> _EphemeralSecretHandle:
        if self._closed:
            raise ConfigurationViolation(
                "SEC-SECRET-CLOSED", "secret handle is already closed"
            )
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<SecretHandle {state}>"

    def __reduce__(self) -> Never:
        raise TypeError("secret handles cannot be serialized")


class EnvironmentFileCredentialPort(CredentialPort):
    """Resolve only v1-approved environment and file locators."""

    __slots__ = ("_environment", "_maximum_bytes", "_secret_roots")

    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        secret_roots: tuple[Path, ...],
        maximum_bytes: int = 65_536,
    ) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self._environment = environment
        self._secret_roots = secret_roots
        self._maximum_bytes = maximum_bytes

    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        if locator.scheme == "env":
            value = self._resolve_environment(locator)
        elif locator.scheme == "file":
            value = self._resolve_file(locator)
        elif locator.scheme in {"os-store", "command"}:
            raise ConfigurationViolation(
                "SEC-SECRET-SCHEME", "credential locator scheme is unsupported"
            )
        else:
            raise ConfigurationViolation(
                "SEC-SECRET-SCHEME", "credential locator scheme is not allowed"
            )
        return _EphemeralSecretHandle(value)

    def _resolve_environment(self, locator: CredentialLocator) -> bytes:
        if _SECRET_ENV_NAME.fullmatch(locator.target) is None:
            raise ConfigurationViolation(
                "SEC-SECRET-ENV", "credential environment name is not allowed"
            )
        value = self._environment.get(locator.target)
        if value is None:
            raise ConfigurationViolation(
                "SEC-SECRET-MISSING", "required credential is unavailable"
            )
        encoded = value.encode("utf-8")
        return self._validate_content(encoded)

    def _resolve_file(self, locator: CredentialLocator) -> bytes:
        candidate, root = require_within_roots(
            Path(locator.target),
            self._secret_roots,
            code="SEC-SECRET-ROOT",
        )
        if has_reparse_point(candidate, root=root):
            raise ConfigurationViolation(
                "SEC-SECRET-REPARSE", "credential path contains a reparse point"
            )
        try:
            metadata = candidate.stat(follow_symlinks=False)
        except OSError:
            raise ConfigurationViolation(
                "SEC-SECRET-MISSING", "required credential is unavailable"
            ) from None
        if not candidate.is_file() or candidate.is_symlink():
            raise ConfigurationViolation(
                "SEC-SECRET-FILE", "credential path is not a regular file"
            )
        if metadata.st_size > self._maximum_bytes:
            raise ConfigurationViolation(
                "SEC-SECRET-SIZE", "credential exceeds the configured size limit"
            )
        try:
            content = candidate.read_bytes()
        except OSError:
            raise ConfigurationViolation(
                "SEC-SECRET-READ", "credential file could not be read"
            ) from None
        return self._validate_content(content)

    def _validate_content(self, content: bytes) -> bytes:
        if len(content) > self._maximum_bytes:
            raise ConfigurationViolation(
                "SEC-SECRET-SIZE", "credential exceeds the configured size limit"
            )
        if content.endswith(b"\r\n"):
            content = content[:-2]
        elif content.endswith(b"\n"):
            content = content[:-1]
        if not content:
            raise ConfigurationViolation(
                "SEC-SECRET-EMPTY", "credential must not be empty"
            )
        return content


__all__ = ("EnvironmentFileCredentialPort",)
