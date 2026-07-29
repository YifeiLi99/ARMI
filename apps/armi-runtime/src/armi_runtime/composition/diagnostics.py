"""Allowlisted UTF-8 JSONL diagnostics for the Runtime process."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from armi_kernel.contracts import Instant

from .runtime_errors import RuntimeViolation

_EVENT = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$", re.ASCII)
_RESULT = re.compile(r"^[A-Z][A-Z0-9_-]{2,127}$", re.ASCII)


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
    ) -> None:
        logger = logging.Logger(f"armi-runtime.{instance_id}", level=logging.INFO)
        logger.propagate = False
        logs_root = data_root / "logs"
        try:
            logs_root.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = logging.FileHandler(
                logs_root / f"runtime-{instance_id}.jsonl",
                encoding="utf-8",
            )
        except OSError:
            handler = logging.StreamHandler(fallback or sys.stderr)
        handler.setFormatter(_JsonLineFormatter())
        logger.addHandler(handler)
        self._logger = logger
        self._handler = handler
        self._base = {
            "service": "armi-runtime",
            "environment_id": environment_id,
            "instance_id": instance_id,
        }

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
        self._handler.flush()
        self._handler.close()
        self._logger.removeHandler(self._handler)


__all__ = ("StructuredDiagnosticLog",)
