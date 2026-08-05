"""Allowlisted UTF-8 JSONL diagnostics with explicit stderr degradation."""

from __future__ import annotations

import json
import logging
import re
import stat
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from armi_kernel.contracts import Instant

from .runtime_errors import RuntimeViolation

_EVENT = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$", re.ASCII)
_RESULT = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}$", re.ASCII)
_DEGRADED_REASON = "RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE"
_LOG_NAME = re.compile(
    r"^runtime-[A-Za-z0-9-]{1,128}(?:\.[0-9]{8}T[0-9]{12}Z\.[0-9]+)?\.jsonl$",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class DiagnosticSinkStatus:
    mode: str
    reason_code: str | None
    current_bytes: int
    retained_bytes: int
    rotations: int
    retention_deleted: int
    retention_failures: int


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = record.msg
        if not isinstance(payload, dict):
            raise RuntimeViolation(
                "LOG-PAYLOAD",
                "structured diagnostics require an allowlisted object",
            )
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class _FailoverHandler(logging.Handler):
    __slots__ = (
        "_active_date",
        "_active_path",
        "_current_bytes",
        "_fallback",
        "_file",
        "_logs_root",
        "_on_degraded",
        "_reason_code",
        "_retention_deleted",
        "_retention_failures",
        "_retention_seconds",
        "_rotation_max_bytes",
        "_rotations",
    )

    def __init__(
        self,
        *,
        file: TextIO | None,
        active_path: Path,
        logs_root: Path,
        rotation_max_bytes: int,
        retention_seconds: int,
        fallback: TextIO,
        on_degraded: Callable[[str], object] | None,
    ) -> None:
        super().__init__()
        self._file = file
        self._active_path = active_path
        self._logs_root = logs_root
        self._rotation_max_bytes = rotation_max_bytes
        self._retention_seconds = retention_seconds
        self._fallback = fallback
        self._on_degraded = on_degraded
        self._reason_code = _DEGRADED_REASON if file is None else None
        self._active_date = datetime.now(UTC).date()
        self._current_bytes = _safe_size(active_path) if file is not None else 0
        self._rotations = 0
        self._retention_deleted = 0
        self._retention_failures = 0
        self._apply_retention()

    @property
    def status(self) -> DiagnosticSinkStatus:
        return DiagnosticSinkStatus(
            mode="stderr" if self._file is None else "file",
            reason_code=self._reason_code,
            current_bytes=self._current_bytes,
            retained_bytes=self._retained_bytes(),
            rotations=self._rotations,
            retention_deleted=self._retention_deleted,
            retention_failures=self._retention_failures,
        )

    def emit(self, record: logging.LogRecord) -> None:
        line = f"{self.format(record)}\n"
        if self._file is not None:
            try:
                file = self._rotate_if_needed(len(line.encode("utf-8")))
                file.write(line)
                file.flush()
                self._current_bytes += len(line.encode("utf-8"))
                return
            except OSError:
                self._degrade()
        try:
            self._fallback.write(line)
            self._fallback.flush()
        except OSError:
            raise RuntimeViolation(
                "LOG-SINK",
                "diagnostic output is unavailable",
            ) from None

    def _rotate_if_needed(self, incoming_bytes: int) -> TextIO:
        file = self._file
        if file is None:
            raise OSError
        now = datetime.now(UTC)
        if self._current_bytes == 0 or (
            now.date() == self._active_date
            and self._current_bytes + incoming_bytes <= self._rotation_max_bytes
        ):
            return file
        file.flush()
        file.close()
        self._file = None
        self._rotations += 1
        timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        rotated = self._active_path.with_name(
            f"{self._active_path.stem}.{timestamp}.{self._rotations}.jsonl"
        )
        self._active_path.replace(rotated)
        file = self._active_path.open("a", encoding="utf-8", newline="\n")
        self._file = file
        self._active_date = now.date()
        self._current_bytes = 0
        self._apply_retention(now=now)
        return file

    def _degrade(self) -> None:
        if self._file is not None:
            with suppress(OSError):
                self._file.close()
        self._file = None
        self._reason_code = _DEGRADED_REASON
        if self._on_degraded is not None:
            self._on_degraded(_DEGRADED_REASON)

    def _apply_retention(self, *, now: datetime | None = None) -> None:
        cutoff = (now or datetime.now(UTC)).timestamp() - self._retention_seconds
        try:
            candidates = tuple(self._logs_root.iterdir())
        except OSError:
            self._retention_failures += 1
            return
        for path in candidates:
            if path == self._active_path or _LOG_NAME.fullmatch(path.name) is None:
                continue
            try:
                metadata = path.lstat()
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or path.is_symlink()
                    or metadata.st_nlink != 1
                    or getattr(metadata, "st_file_attributes", 0) & 0x400
                    or metadata.st_mtime > cutoff
                ):
                    continue
                path.unlink()
                self._retention_deleted += 1
            except OSError:
                self._retention_failures += 1

    def _retained_bytes(self) -> int:
        total = 0
        try:
            candidates = self._logs_root.iterdir()
            for path in candidates:
                if _LOG_NAME.fullmatch(path.name) is None:
                    continue
                metadata = path.lstat()
                if (
                    stat.S_ISREG(metadata.st_mode)
                    and not path.is_symlink()
                    and metadata.st_nlink == 1
                    and not getattr(metadata, "st_file_attributes", 0) & 0x400
                ):
                    total += metadata.st_size
        except OSError:
            return self._current_bytes
        return total

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                self._file = None
                self._reason_code = _DEGRADED_REASON
        super().close()


class StructuredDiagnosticLog:
    """Emit only lifecycle facts; arbitrary context cannot enter the log."""

    __slots__ = ("_base", "_handler", "_logger")

    def __init__(
        self,
        *,
        data_root: Path,
        environment_id: str,
        instance_id: str,
        fallback: TextIO | None = None,
        on_degraded: Callable[[str], object] | None = None,
        rotation_max_bytes: int = 16_777_216,
        retention_seconds: int = 604_800,
    ) -> None:
        if (
            type(rotation_max_bytes) is not int
            or rotation_max_bytes <= 0
            or type(retention_seconds) is not int
            or retention_seconds <= 0
        ):
            raise RuntimeViolation("LOG-CONFIG", "diagnostic retention is invalid")
        logger = logging.Logger(f"armi-runtime.{instance_id}", level=logging.INFO)
        logger.propagate = False
        logs_root = data_root / "logs"
        stream: TextIO | None = None
        active_path = logs_root / f"runtime-{instance_id}.jsonl"
        try:
            logs_root.mkdir(parents=True, exist_ok=True)
            root_metadata = logs_root.lstat()
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or logs_root.is_symlink()
                or getattr(root_metadata, "st_file_attributes", 0) & 0x400
            ):
                raise OSError
            stream = active_path.open(
                "a",
                encoding="utf-8",
                newline="\n",
            )
        except OSError:
            stream = None
        handler = _FailoverHandler(
            file=stream,
            active_path=active_path,
            logs_root=logs_root,
            rotation_max_bytes=rotation_max_bytes,
            retention_seconds=retention_seconds,
            fallback=fallback or sys.stderr,
            on_degraded=on_degraded,
        )
        handler.setFormatter(_JsonLineFormatter())
        logger.addHandler(handler)
        self._logger = logger
        self._handler = handler
        self._base = {
            "service": "armi-runtime",
            "environment_id": environment_id,
            "instance_id": instance_id,
        }

    @property
    def status(self) -> DiagnosticSinkStatus:
        return self._handler.status

    def emit(
        self,
        event: str,
        *,
        level: int = logging.INFO,
        result_code: str | None = None,
        duration_ms: int | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        if _EVENT.fullmatch(event) is None:
            raise RuntimeViolation("LOG-EVENT", "diagnostic event name is invalid")
        if result_code is not None and _RESULT.fullmatch(result_code) is None:
            raise RuntimeViolation("LOG-RESULT", "diagnostic result code is invalid")
        if duration_ms is not None and duration_ms < 0:
            raise RuntimeViolation("LOG-DURATION", "duration must be non-negative")
        if any(_RESULT.fullmatch(code) is None for code in reason_codes):
            raise RuntimeViolation("LOG-RESULT", "diagnostic reason code is invalid")
        payload: dict[str, object] = {
            **self._base,
            "timestamp": Instant(datetime.now(UTC)).to_wire(),
            "level": logging.getLevelName(level).lower(),
            "event": event,
            "message": event,
        }
        if result_code is not None:
            payload["result_code"] = result_code
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if reason_codes:
            payload["reason_codes"] = list(reason_codes)
        self._logger.log(level, payload)

    def close(self) -> None:
        self._handler.close()
        self._logger.removeHandler(self._handler)


def _safe_size(path: Path) -> int:
    try:
        metadata = path.stat()
    except OSError:
        return 0
    return metadata.st_size


__all__ = (
    "DiagnosticSinkStatus",
    "StructuredDiagnosticLog",
)
