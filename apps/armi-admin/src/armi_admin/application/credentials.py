"""Admin-only env/file secret resolution without a Runtime dependency."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from armi_kernel.application import CredentialLocator, CredentialPort, CredentialPurpose

_ResultT = TypeVar("_ResultT")
_MAX_SECRET_BYTES = 16 * 1024


class AdminSecretError(RuntimeError):
    """A stable error that never includes a locator target or secret."""


class _SecretHandle:
    __slots__ = ("_buffer", "_closed")

    def __init__(self, value: bytes) -> None:
        self._buffer = bytearray(value)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def consume(self, operation: Callable[[memoryview], _ResultT]) -> _ResultT:
        if self._closed:
            raise AdminSecretError("ADMIN-SECRET-CLOSED")
        return operation(memoryview(self._buffer).toreadonly())

    def close(self) -> None:
        if not self._closed:
            self._buffer[:] = b"\x00" * len(self._buffer)
            self._closed = True

    def __enter__(self) -> _SecretHandle:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(closed={self.closed}, value=<redacted>)"


class AdminCredentialPort(CredentialPort):
    """Resolve only explicitly configured Admin-process credentials."""

    __slots__ = ("_config_root", "_environ", "_locators")

    def __init__(
        self,
        *,
        locator: CredentialLocator,
        migrator_locator: CredentialLocator | None = None,
        preview_locator: CredentialLocator | None = None,
        config_root: Path,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._locators = {
            "database.admin": locator,
            "database.migrator": migrator_locator or locator,
            "admin.preview": preview_locator or locator,
            "admin.correction.preview": preview_locator or locator,
        }
        self._config_root = config_root.resolve(strict=True)
        self._environ = os.environ if environ is None else environ

    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> _SecretHandle:
        if self._locators.get(purpose.value) != locator:
            raise AdminSecretError("ADMIN-SECRET-SCOPE")
        if locator.scheme == "env":
            value = self._environ.get(locator.target, "").encode("utf-8")
        elif locator.scheme == "file":
            value = self._read_file(locator.target)
        else:
            raise AdminSecretError("ADMIN-SECRET-SCHEME")
        if not value or len(value) > _MAX_SECRET_BYTES or b"\x00" in value:
            raise AdminSecretError("ADMIN-SECRET-VALUE")
        return _SecretHandle(value.rstrip(b"\r\n"))

    def _read_file(self, target: str) -> bytes:
        try:
            candidate = Path(target)
            if not candidate.is_absolute() or candidate.is_symlink():
                raise AdminSecretError("ADMIN-SECRET-FILE")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self._config_root):
                raise AdminSecretError("ADMIN-SECRET-SCOPE")
            if not resolved.is_file() or resolved.stat().st_size > _MAX_SECRET_BYTES:
                raise AdminSecretError("ADMIN-SECRET-FILE")
            return resolved.read_bytes()
        except AdminSecretError:
            raise
        except Exception as exc:
            raise AdminSecretError("ADMIN-SECRET-FILE") from exc


__all__ = ("AdminCredentialPort", "AdminSecretError")
