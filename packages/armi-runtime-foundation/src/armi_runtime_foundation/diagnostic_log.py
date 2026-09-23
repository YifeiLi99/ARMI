"""Process-owned structured files and standard-library logging integration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, TextIO, cast
from uuid import uuid7

from armi_kernel.application import diagnostic_context

from .diagnostic_redaction import exception_evidence, redact, safe_text
from .diagnostic_stream import DiagnosticTextStream


def _segment_lease(path: Path, *, create: bool = False) -> BinaryIO:
    handle = open(path, "x+b" if create else "r+b")  # noqa: SIM115 -- caller owns the OS lease lifetime
    try:
        if create:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        raise


@dataclass(frozen=True, slots=True)
class DiagnosticSinkStatus:
    mode: str
    reason_code: str | None
    current_bytes: int
    retained_bytes: int
    rotations: int
    retention_deleted: int
    retention_failures: int


class DiagnosticLog(logging.Handler):
    """A single writer per process; protocol stdout is never touched."""

    def __init__(
        self,
        *,
        data_root: Path,
        environment_id: str,
        instance_id: str,
        service: str = "armi-runtime",
        version: str = "source",
        fallback: TextIO | None = None,
        on_degraded: Callable[[str], object] | None = None,
        emergency_root: Path | None = None,
        rotation_max_bytes: int = 16777216,
        retention_seconds: int = 2592000,
        total_max_bytes: int = 1073741824,
        retention_roots: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(logging.INFO)
        self._write_lock = threading.RLock()
        self.root = data_root / "logs"
        self.emergency_root = emergency_root
        self.roots = tuple(dict.fromkeys((self.root, *retention_roots)))
        self.base = {
            "schema_kind": "armi.diagnostic-event",
            "service": service,
            "environment_id": environment_id,
            "instance_id": instance_id,
            "run_id": instance_id,
            "pid": os.getpid(),
            "version": version,
        }
        self.rotation_max_bytes = rotation_max_bytes
        self.retention_seconds = retention_seconds
        self.total_max_bytes = total_max_bytes
        self.fallback = fallback or sys.stderr
        self.on_degraded = on_degraded
        self.sequence = 0
        self.current_bytes = 0
        self.rotations = 0
        self.retention_deleted = 0
        self.retention_failures = 0
        self._last_cleanup = time.monotonic()
        self.mode = "file"
        self.reason: str | None = None
        self.stream: TextIO | None = None
        self._lease: BinaryIO | None = None
        self.path: Path | None = None
        self.counts: Counter[str] = Counter()
        self.error_groups: Counter[str] = Counter()
        self.first_at: str | None = None
        self.last_at: str | None = None
        self._date = datetime.now(UTC).date()
        self._installed = False
        self._open(self.root)

    def _open(self, root: Path) -> None:
        try:
            root.mkdir(parents=True, exist_ok=True)
            if (
                root.is_symlink()
                or getattr(root.stat(), "st_file_attributes", 0) & 0x400
            ):
                raise OSError("diagnostic directory is a reparse point")
            prefix = str(self.base["service"]).removeprefix("armi-")
            self.path = root / f"{prefix}-{self.base['run_id']}-{uuid7()}.jsonl"
            self._lease = _segment_lease(self.path.with_suffix(".lease"), create=True)
            self.stream = self.path.open("x", encoding="utf-8", newline="\n")
            self.current_bytes = 0
        except OSError:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            self.stream = None
            self._degrade()

    def _degrade(self) -> None:
        self.reason = "RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE"
        self.mode = "stderr"
        if self.on_degraded:
            self.on_degraded(self.reason)
        if self.emergency_root is not None and self.root != self.emergency_root:
            emergency = self.emergency_root
            self.emergency_root = None
            self._open(emergency)
            if self.stream is not None:
                self.mode = "emergency"

    def _seal(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.flush()
        finally:
            try:
                self.stream.close()
            finally:
                self.stream = None
                if self._lease is not None:
                    self._lease.close()
                    self._lease = None
        if self.path is not None:
            self.path.with_suffix(".summary.json").write_text(
                json.dumps(
                    {
                        "levels": dict(self.counts),
                        "bytes": self.current_bytes,
                        "run_id": self.base["run_id"],
                        "environment_id": self.base["environment_id"],
                        "first_at": self.first_at,
                        "last_at": self.last_at,
                        "error_groups": dict(self.error_groups),
                    }
                ),
                encoding="utf-8",
            )
        self.counts.clear()
        self.error_groups.clear()
        self.first_at = self.last_at = None

    def _retention(self) -> None:
        self._last_cleanup = time.monotonic()
        # OS leases are released on crashes too. Never unlink an active writer.
        try:
            paths = [
                p
                for root in self.roots
                if root.is_dir()
                for p in (*root.glob("*.jsonl"), *root.glob("query-*.cursor"))
                if not p.is_symlink()
            ]
            total = sum(p.stat().st_size for p in paths)
            cutoff = time.time() - self.retention_seconds
            for path in sorted(paths, key=lambda p: p.stat().st_mtime):
                if path.suffix == ".cursor":
                    size = path.stat().st_size
                    if path.stat().st_mtime < cutoff or total > self.total_max_bytes:
                        path.unlink(missing_ok=True)
                        total -= size
                    continue
                summary = path.with_suffix(".summary.json")
                lease_path = path.with_suffix(".lease")
                if path == self.path or (
                    not summary.is_file() and not lease_path.is_file()
                ):
                    continue
                size = path.stat().st_size
                if path.stat().st_mtime < cutoff or total > self.total_max_bytes:
                    lease: BinaryIO | None = None
                    try:
                        if lease_path.is_file():
                            lease = _segment_lease(lease_path)
                    except OSError:
                        continue
                    try:
                        path.unlink(missing_ok=True)
                        summary.unlink(missing_ok=True)
                    finally:
                        if lease is not None:
                            lease.close()
                    lease_path.unlink(missing_ok=True)
                    total -= size
                    self.retention_deleted += 1
        except OSError:
            self.retention_failures += 1
        # Reconstructable operational metadata, never a business fact or database table.
        try:
            self.root.joinpath("retention.status.json").write_text(
                json.dumps(
                    {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "retention_seconds": self.retention_seconds,
                        "total_max_bytes": self.total_max_bytes,
                        "deleted_segments_this_run": self.retention_deleted,
                        "cleanup_failures_this_run": self.retention_failures,
                        "retained_bytes": self.status.retained_bytes,
                        "quota_exceeded": self.status.retained_bytes
                        > self.total_max_bytes,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            self.retention_failures += 1

    @property
    def active_stream(self) -> TextIO | None:
        return self.stream

    @property
    def status(self) -> DiagnosticSinkStatus:
        try:
            retained = sum(
                p.stat().st_size
                for root in self.roots
                if root.is_dir()
                for p in (*root.glob("*.jsonl"), *root.glob("query-*.cursor"))
                if not p.is_symlink()
            )
        except OSError:
            retained = self.current_bytes
        return DiagnosticSinkStatus(
            self.mode,
            self.reason,
            self.current_bytes,
            retained,
            self.rotations,
            self.retention_deleted,
            self.retention_failures,
        )

    def write(
        self,
        event: str,
        *,
        level: int = logging.INFO,
        message: str | None = None,
        error: BaseException | None = None,
        context: dict[str, str] | None = None,
        source: dict[str, object] | None = None,
        **fields: object,
    ) -> str:
        with self._write_lock:
            self.sequence += 1
            event_id = str(uuid7())
            value = {
                **self.base,
                "event_id": event_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "sequence": self.sequence,
                "level": logging.getLevelName(level).lower(),
                "event": event,
                "message": message or event,
                "component": event.split(".", 1)[0],
                "sink_mode": self.mode,
                "sink_reason": self.reason,
                "correlation": context if context is not None else diagnostic_context(),
                **fields,
            }
            if source:
                value["source"] = source
            if error is not None:
                value["exception"] = exception_evidence(error)
            value = cast(dict[str, object], redact(value))
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            original_size = len(encoded.encode("utf-8"))
            if original_size > 65535:
                value = {
                    key: value[key]
                    for key in (
                        "schema_kind",
                        "event_id",
                        "timestamp",
                        "sequence",
                        "level",
                        "event",
                        "service",
                        "run_id",
                        "environment_id",
                        "correlation",
                    )
                }
                value["truncation"] = {
                    "original_bytes": original_size,
                    "omitted_fields": "message,details,exception,source",
                }
                value["correlation"] = {
                    key: safe_text(str(item), 128)
                    for key, item in cast(
                        dict[str, object], value["correlation"]
                    ).items()
                }
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            line = encoded + "\n"
            size = len(line.encode("utf-8"))
            if self.stream is not None:
                try:
                    today = datetime.now(UTC).date()
                    if self.current_bytes and (
                        self.current_bytes + size > self.rotation_max_bytes
                        or today != self._date
                    ):
                        self._seal()
                        self.rotations += 1
                        self._date = today
                        self._open(self.root)
                        self._retention()
                    active_stream = self.active_stream
                    if active_stream is not None:
                        active_stream.write(line)
                        active_stream.flush()
                        self.current_bytes += size
                        if time.monotonic() - self._last_cleanup >= 60:
                            self._retention()
                        self.counts[logging.getLevelName(level).lower()] += 1
                        self.first_at = self.first_at or str(value["timestamp"])
                        self.last_at = str(value["timestamp"])
                        if level >= logging.WARNING:
                            group = json.dumps(
                                [
                                    value["event"],
                                    value.get("result_code"),
                                    type(error).__name__ if error else None,
                                ]
                            )
                            if (
                                len(self.error_groups) < 256
                                or group in self.error_groups
                            ):
                                self.error_groups[group] += 1
                            else:
                                self.error_groups["overflow"] += 1
                        return event_id
                except OSError:
                    failed_stream = self.active_stream
                    self.stream = None
                    if failed_stream is not None:
                        with suppress(OSError):
                            failed_stream.close()
                    if self._lease is not None:
                        self._lease.close()
                        self._lease = None
                    self._degrade()
                    emergency_stream = self.stream
                    if emergency_stream is not None:
                        try:
                            value["sink_mode"] = self.mode
                            value["sink_reason"] = self.reason
                            line = (
                                json.dumps(
                                    value, ensure_ascii=False, separators=(",", ":")
                                )
                                + "\n"
                            )
                            emergency_stream.write(line)
                            emergency_stream.flush()
                            self.current_bytes += size
                            return event_id
                        except OSError:
                            with suppress(OSError):
                                emergency_stream.close()
                            if self._lease is not None:
                                self._lease.close()
                                self._lease = None
                            self.stream = None
            try:
                if self.fallback is None:
                    raise OSError("stderr unavailable")
                self.fallback.write(line)
                self.fallback.flush()
            except OSError, ValueError:
                self.mode = "unavailable"
            return event_id

    def emit(self, record: logging.LogRecord) -> None:
        self.write(
            getattr(record, "armi_event", "python.log"),
            level=record.levelno,
            message=record.getMessage(),
            error=record.exc_info[1] if record.exc_info else None,
            context=getattr(record, "diagnostic_context", diagnostic_context()),
            source={
                "file": Path(record.pathname).name,
                "line": record.lineno,
                "function": record.funcName,
                "logger": record.name,
            },
            details=getattr(record, "armi_details", {}),
            component=record.name.removeprefix("armi."),
        )

    def install(self, *, capture_output: bool = False) -> None:
        if self._installed:
            return
        self._installed = True
        self._saved_streams = (sys.stdout, sys.stderr) if capture_output else None
        if capture_output:
            sys.stdout = DiagnosticTextStream("stdout")
            sys.stderr = DiagnosticTextStream("stderr")
        self._root_level = logging.getLogger().level
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(self)
        self._excepthook = sys.excepthook
        self._thread_hook = threading.excepthook

        def uncaught(
            kind: type[BaseException], error: BaseException, tb: TracebackType | None
        ) -> None:
            self.write("process.unhandled_exception", level=logging.ERROR, error=error)

        def thread_error(args: threading.ExceptHookArgs) -> None:
            self.write(
                "thread.unhandled_exception",
                level=logging.ERROR,
                error=args.exc_value,
                thread_name=args.thread.name if args.thread else None,
            )

        sys.excepthook = uncaught
        threading.excepthook = thread_error
        logging.captureWarnings(True)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        else:
            self._loop = loop
            self._loop_handler = loop.get_exception_handler()
            loop.set_exception_handler(
                lambda _loop, context: self.write(
                    "asyncio.unhandled_exception",
                    level=logging.ERROR,
                    message=safe_text(str(context.get("message", "asyncio failure"))),
                    error=context.get("exception"),
                )
            )

    def close(self) -> None:
        if self._installed:
            if self._saved_streams is not None:
                sys.stdout.flush()
                sys.stderr.flush()
                sys.stdout, sys.stderr = self._saved_streams
                self._saved_streams = None
            logging.getLogger().removeHandler(self)
            logging.getLogger().setLevel(self._root_level)
            sys.excepthook = self._excepthook
            threading.excepthook = self._thread_hook
            if self._loop is not None and not self._loop.is_closed():
                self._loop.set_exception_handler(self._loop_handler)
            self._installed = False
        try:
            self._seal()
            self._retention()
        except OSError:
            self.reason = "RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE"
        super().close()
