"""Process-local sampling for private Runtime status and later capacity gates."""

from __future__ import annotations

import asyncio
import copy
import ctypes
import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from armi_kernel.contracts import Instant

from armi_runtime.adapters.persistence.runtime_observability import (
    DatabaseObservation,
    RuntimeObservationError,
)

from .diagnostics import DiagnosticSinkStatus


def _ignore_diagnostic(_event: str) -> None:
    return None


class RuntimeObservationPort(Protocol):
    async def open(self) -> None: ...

    async def collect(self) -> DatabaseObservation: ...

    async def close(self) -> None: ...


class RuntimeObservationDriver:
    """Keep one bounded latest sample; metrics never become business truth."""

    __slots__ = (
        "_critical_free_bytes",
        "_data_root",
        "_diagnostic",
        "_diagnostic_status",
        "_interval_seconds",
        "_last_signal",
        "_port",
        "_snapshot",
        "_started_monotonic",
        "_stop",
        "_warning_free_bytes",
    )

    def __init__(
        self,
        port: RuntimeObservationPort,
        *,
        data_root: Path,
        sample_interval_seconds: int,
        disk_warning_free_bytes: int,
        disk_critical_free_bytes: int,
        diagnostic_status: Callable[[], DiagnosticSinkStatus],
        diagnostic: Callable[[str], None] | None = None,
    ) -> None:
        if (
            not data_root.is_absolute()
            or type(sample_interval_seconds) is not int
            or sample_interval_seconds <= 0
            or type(disk_warning_free_bytes) is not int
            or type(disk_critical_free_bytes) is not int
            or disk_critical_free_bytes <= 0
            or disk_warning_free_bytes <= disk_critical_free_bytes
        ):
            raise ValueError("runtime observation configuration is invalid")
        self._port = port
        self._data_root = data_root
        self._interval_seconds = sample_interval_seconds
        self._warning_free_bytes = disk_warning_free_bytes
        self._critical_free_bytes = disk_critical_free_bytes
        self._diagnostic_status = diagnostic_status
        emit: Callable[[str], None] = diagnostic or _ignore_diagnostic
        self._diagnostic = emit
        self._started_monotonic = time.monotonic()
        self._stop = asyncio.Event()
        self._last_signal: str | None = None
        self._snapshot: dict[str, object] = self._unavailable_snapshot(
            "OBSERVABILITY_NOT_SAMPLED"
        )

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.collect_once()
            try:
                async with asyncio.timeout(self._interval_seconds):
                    await self._stop.wait()
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self._port.close()

    def snapshot(self) -> dict[str, object]:
        return copy.deepcopy(self._snapshot)

    async def collect_once(self) -> None:
        try:
            database = await self._port.collect()
            disk = shutil.disk_usage(self._data_root)
            disk_state = _disk_state(
                disk.free,
                warning=self._warning_free_bytes,
                critical=self._critical_free_bytes,
            )
            diagnostic = self._diagnostic_status()
            snapshot: dict[str, object] = {
                "schema_version": "armi.runtime-observability.v1",
                "status": "available",
                "observed_at": Instant(datetime.now(UTC)).to_wire(),
                "authority": {
                    "active_runtime_count": database.active_runtime_count,
                    "heartbeat_age_seconds": database.runtime_heartbeat_age_seconds,
                },
                "backlog": {
                    "work": _backlog(
                        database.work_counts,
                        database.work_oldest_open_seconds,
                    ),
                    "outbox": _backlog(
                        database.outbox_counts,
                        database.outbox_oldest_open_seconds,
                    ),
                    "effects": _backlog(
                        database.effect_counts,
                        database.effect_oldest_open_seconds,
                    ),
                },
                "resources": {
                    "process_rss_bytes": _process_rss_bytes(),
                    "process_cpu_milliseconds": int(time.process_time() * 1000),
                    "process_uptime_seconds": max(
                        0, int(time.monotonic() - self._started_monotonic)
                    ),
                    "database_bytes": database.database_bytes,
                    "artifact_bytes": database.artifact_bytes,
                    "artifact_counts": dict(database.artifact_counts),
                    "disk_total_bytes": disk.total,
                    "disk_free_bytes": disk.free,
                    "disk_state": disk_state,
                },
                "diagnostics": {
                    "sink": diagnostic.mode,
                    "current_bytes": diagnostic.current_bytes,
                    "retained_bytes": diagnostic.retained_bytes,
                    "rotations": diagnostic.rotations,
                    "retention_deleted": diagnostic.retention_deleted,
                    "retention_failures": diagnostic.retention_failures,
                },
            }
            self._snapshot = snapshot
            signal = (
                "runtime.resource.disk_critical"
                if disk_state == "critical"
                else (
                    "runtime.resource.disk_warning" if disk_state == "warning" else None
                )
            )
        except RuntimeObservationError, OSError:
            self._snapshot = self._unavailable_snapshot(
                "OBSERVABILITY_SAMPLE_UNAVAILABLE"
            )
            signal = "runtime.observability.unavailable"
        if signal != self._last_signal:
            if signal is not None:
                self._diagnostic(signal)
            self._last_signal = signal

    def _unavailable_snapshot(self, reason: str) -> dict[str, object]:
        return {
            "schema_version": "armi.runtime-observability.v1",
            "status": "unavailable",
            "observed_at": Instant(datetime.now(UTC)).to_wire(),
            "reason_code": reason,
        }


def _backlog(
    counts: tuple[tuple[str, int], ...], oldest_open_seconds: int | None
) -> dict[str, object]:
    return {
        "counts": dict(counts),
        "oldest_open_age_seconds": oldest_open_seconds,
    }


def _disk_state(free: int, *, warning: int, critical: int) -> str:
    if free <= critical:
        return "critical"
    if free <= warning:
        return "warning"
    return "ok"


def _process_rss_bytes() -> int | None:
    if os.name == "nt":
        return _windows_process_rss_bytes()
    try:
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except ImportError, OSError, ValueError:
        return None
    return rss if sys_platform_is_macos() else rss * 1024


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


def _windows_process_rss_bytes() -> int | None:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            return None
        return int(counters.WorkingSetSize)
    except AttributeError, OSError, ValueError:
        return None


__all__ = ("RuntimeObservationDriver", "RuntimeObservationPort")
