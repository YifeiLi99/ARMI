"""Early process logging without requiring a database or a running Runtime."""

from __future__ import annotations

import atexit
import logging
from pathlib import Path
from uuid import uuid7

from .diagnostic_log import DiagnosticLog


def bootstrap_diagnostics(
    *,
    root: Path,
    environment_id: str,
    service: str,
    version: str = "source",
    instance_id: str | None = None,
    retention_roots: tuple[Path, ...] = (),
) -> DiagnosticLog:
    for handler in logging.getLogger().handlers:
        if (
            isinstance(handler, DiagnosticLog)
            and handler.base["environment_id"] == environment_id
        ):
            return handler
    sink = DiagnosticLog(
        data_root=root,
        environment_id=environment_id,
        instance_id=instance_id or str(uuid7()),
        service=service,
        version=version,
        retention_roots=retention_roots,
    )
    sink.install()
    sink.write("process.started", details={"component": service})
    atexit.register(sink.close)
    return sink
