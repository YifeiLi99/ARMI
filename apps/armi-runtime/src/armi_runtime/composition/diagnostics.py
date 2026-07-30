"""Allowlisted UTF-8 JSONL diagnostics with explicit stderr degradation."""

from __future__ import annotations

import json
import logging
import re
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


@dataclass(frozen=True, slots=True)
class DiagnosticSinkStatus:
    mode: str
    reason_code: str | None


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
    __slots__ = ("_fallback", "_file", "_on_degraded", "_reason_code")

    def __init__(
        self,
        *,
        file: TextIO | None,
        fallback: TextIO,
        on_degraded: Callable[[str], object] | None,
    ) -> None:
        super().__init__()
        self._file = file
        self._fallback = fallback
        self._on_degraded = on_degraded
        self._reason_code = _DEGRADED_REASON if file is None else None

    @property
    def status(self) -> DiagnosticSinkStatus:
        return DiagnosticSinkStatus(
            mode="stderr" if self._file is None else "file",
            reason_code=self._reason_code,
        )

    def emit(self, record: logging.LogRecord) -> None:
        line = f"{self.format(record)}\n"
        if self._file is not None:
            try:
                self._file.write(line)
                self._file.flush()
                return
            except OSError:
                with suppress(OSError):
                    self._file.close()
                self._file = None
                self._reason_code = _DEGRADED_REASON
                if self._on_degraded is not None:
                    self._on_degraded(_DEGRADED_REASON)
        try:
            self._fallback.write(line)
            self._fallback.flush()
        except OSError:
            raise RuntimeViolation(
                "LOG-SINK",
                "diagnostic output is unavailable",
            ) from None

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
    ) -> None:
        logger = logging.Logger(f"armi-runtime.{instance_id}", level=logging.INFO)
        logger.propagate = False
        logs_root = data_root / "logs"
        stream: TextIO | None = None
        try:
            logs_root.mkdir(parents=True, exist_ok=True)
            stream = (logs_root / f"runtime-{instance_id}.jsonl").open(
                "a",
                encoding="utf-8",
                newline="\n",
            )
        except OSError:
            stream = None
        handler = _FailoverHandler(
            file=stream,
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


__all__ = (
    "DiagnosticSinkStatus",
    "StructuredDiagnosticLog",
)
