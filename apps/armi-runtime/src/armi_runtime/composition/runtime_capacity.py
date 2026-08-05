"""Bounded short-run capacity sampling over the private Runtime status contract."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from .runtime_errors import RuntimeViolation


@dataclass(frozen=True, slots=True)
class RuntimeCapacitySample:
    offset_milliseconds: int
    observed_at: str
    runtime_state: str
    readiness: str
    active_runtime_count: int
    heartbeat_age_seconds: int | None
    work_open: int
    work_oldest_open_age_seconds: int | None
    outbox_open: int
    outbox_oldest_open_age_seconds: int | None
    effects_open: int
    effects_oldest_open_age_seconds: int | None
    process_rss_bytes: int | None
    process_cpu_milliseconds: int
    process_uptime_seconds: int
    database_bytes: int
    artifact_bytes: int
    disk_free_bytes: int
    disk_state: str
    diagnostic_retained_bytes: int

    @property
    def open_backlog(self) -> int:
        return self.work_open + self.outbox_open + self.effects_open

    def safe_view(self) -> dict[str, object]:
        return {
            "offset_milliseconds": self.offset_milliseconds,
            "observed_at": self.observed_at,
            "runtime_state": self.runtime_state,
            "readiness": self.readiness,
            "authority": {
                "active_runtime_count": self.active_runtime_count,
                "heartbeat_age_seconds": self.heartbeat_age_seconds,
            },
            "backlog": {
                "work_open": self.work_open,
                "work_oldest_open_age_seconds": (self.work_oldest_open_age_seconds),
                "outbox_open": self.outbox_open,
                "outbox_oldest_open_age_seconds": (self.outbox_oldest_open_age_seconds),
                "effects_open": self.effects_open,
                "effects_oldest_open_age_seconds": (
                    self.effects_oldest_open_age_seconds
                ),
                "total_open": self.open_backlog,
            },
            "resources": {
                "process_rss_bytes": self.process_rss_bytes,
                "process_cpu_milliseconds": self.process_cpu_milliseconds,
                "process_uptime_seconds": self.process_uptime_seconds,
                "database_bytes": self.database_bytes,
                "artifact_bytes": self.artifact_bytes,
                "disk_free_bytes": self.disk_free_bytes,
                "disk_state": self.disk_state,
                "diagnostic_retained_bytes": self.diagnostic_retained_bytes,
            },
        }


@dataclass(frozen=True, slots=True)
class RuntimeCapacityReport:
    requested_duration_seconds: int
    sample_interval_seconds: int
    max_rss_growth_bytes: int
    max_backlog_growth: int
    max_open_backlog_age_seconds: int
    max_log_growth_bytes: int
    samples: tuple[RuntimeCapacitySample, ...]
    unavailable_reasons: tuple[str, ...]
    issue_codes: tuple[str, ...]

    @property
    def status(self) -> str:
        return "pass" if not self.issue_codes else "attention"

    def safe_view(self) -> dict[str, object]:
        first = self.samples[0]
        last = self.samples[-1]
        rss_values = tuple(
            sample.process_rss_bytes
            for sample in self.samples
            if sample.process_rss_bytes is not None
        )
        return {
            "schema_version": "armi.runtime-capacity-baseline.v1",
            "status": self.status,
            "requested_duration_seconds": self.requested_duration_seconds,
            "sample_interval_seconds": self.sample_interval_seconds,
            "sample_count": len(self.samples),
            "unavailable_sample_count": len(self.unavailable_reasons),
            "unavailable_reasons": list(self.unavailable_reasons),
            "issue_codes": list(self.issue_codes),
            "thresholds": {
                "max_rss_growth_bytes": self.max_rss_growth_bytes,
                "max_backlog_growth": self.max_backlog_growth,
                "max_open_backlog_age_seconds": (self.max_open_backlog_age_seconds),
                "max_log_growth_bytes": self.max_log_growth_bytes,
            },
            "deltas": {
                "process_rss_bytes": _optional_delta(
                    first.process_rss_bytes,
                    last.process_rss_bytes,
                ),
                "process_cpu_milliseconds": (
                    last.process_cpu_milliseconds - first.process_cpu_milliseconds
                ),
                "database_bytes": last.database_bytes - first.database_bytes,
                "artifact_bytes": last.artifact_bytes - first.artifact_bytes,
                "diagnostic_retained_bytes": (
                    last.diagnostic_retained_bytes - first.diagnostic_retained_bytes
                ),
                "open_backlog": last.open_backlog - first.open_backlog,
            },
            "maxima": {
                "process_rss_bytes": max(rss_values) if rss_values else None,
                "open_backlog": max(sample.open_backlog for sample in self.samples),
                "work_oldest_open_age_seconds": _optional_max(
                    sample.work_oldest_open_age_seconds for sample in self.samples
                ),
                "outbox_oldest_open_age_seconds": _optional_max(
                    sample.outbox_oldest_open_age_seconds for sample in self.samples
                ),
                "effects_oldest_open_age_seconds": _optional_max(
                    sample.effects_oldest_open_age_seconds for sample in self.samples
                ),
            },
            "minimum_disk_free_bytes": min(
                sample.disk_free_bytes for sample in self.samples
            ),
            "samples": [sample.safe_view() for sample in self.samples],
        }


def run_runtime_capacity_baseline(
    status_source: Callable[[], dict[str, Any]],
    *,
    duration_seconds: int,
    sample_interval_seconds: int,
    max_rss_growth_bytes: int,
    max_backlog_growth: int,
    max_open_backlog_age_seconds: int,
    max_log_growth_bytes: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RuntimeCapacityReport:
    """Sample one already-running Runtime without creating business load."""

    _validate_declaration(
        duration_seconds=duration_seconds,
        sample_interval_seconds=sample_interval_seconds,
        max_rss_growth_bytes=max_rss_growth_bytes,
        max_backlog_growth=max_backlog_growth,
        max_open_backlog_age_seconds=max_open_backlog_age_seconds,
        max_log_growth_bytes=max_log_growth_bytes,
    )
    offsets = list(range(0, duration_seconds, sample_interval_seconds))
    if not offsets or offsets[-1] != duration_seconds:
        offsets.append(duration_seconds)
    started = monotonic()
    samples: list[RuntimeCapacitySample] = []
    unavailable: list[str] = []
    for offset in offsets:
        remaining = started + offset - monotonic()
        if remaining > 0:
            sleep(remaining)
        elapsed_milliseconds = max(0, int((monotonic() - started) * 1000))
        try:
            samples.append(_sample(status_source(), elapsed_milliseconds))
        except RuntimeViolation as error:
            unavailable.append(error.code)
    if not samples:
        raise RuntimeViolation(
            "CAPACITY-OBSERVABILITY-UNAVAILABLE",
            "runtime capacity sampling produced no usable observation",
        )
    issues = _issues(
        samples,
        unavailable=unavailable,
        max_rss_growth_bytes=max_rss_growth_bytes,
        max_backlog_growth=max_backlog_growth,
        max_open_backlog_age_seconds=max_open_backlog_age_seconds,
        max_log_growth_bytes=max_log_growth_bytes,
    )
    return RuntimeCapacityReport(
        requested_duration_seconds=duration_seconds,
        sample_interval_seconds=sample_interval_seconds,
        max_rss_growth_bytes=max_rss_growth_bytes,
        max_backlog_growth=max_backlog_growth,
        max_open_backlog_age_seconds=max_open_backlog_age_seconds,
        max_log_growth_bytes=max_log_growth_bytes,
        samples=tuple(samples),
        unavailable_reasons=tuple(unavailable),
        issue_codes=issues,
    )


def _validate_declaration(
    *,
    duration_seconds: int,
    sample_interval_seconds: int,
    max_rss_growth_bytes: int,
    max_backlog_growth: int,
    max_open_backlog_age_seconds: int,
    max_log_growth_bytes: int,
) -> None:
    if (
        type(duration_seconds) is not int
        or not 1 <= duration_seconds <= 900
        or type(sample_interval_seconds) is not int
        or not 1 <= sample_interval_seconds <= min(60, duration_seconds)
        or type(max_rss_growth_bytes) is not int
        or max_rss_growth_bytes < 0
        or type(max_backlog_growth) is not int
        or max_backlog_growth < 0
        or type(max_open_backlog_age_seconds) is not int
        or max_open_backlog_age_seconds <= 0
        or type(max_log_growth_bytes) is not int
        or max_log_growth_bytes < 0
    ):
        raise RuntimeViolation(
            "CAPACITY-DECLARATION",
            "runtime capacity baseline declaration is invalid",
        )


def _sample(status: dict[str, Any], offset_milliseconds: int) -> RuntimeCapacitySample:
    if status.get("status") != "running":
        raise RuntimeViolation(
            "CAPACITY-RUNTIME-NOT-RUNNING",
            "runtime is not running",
        )
    runtime = _mapping(status.get("runtime"))
    observation = _mapping(runtime.get("observability"))
    if observation.get("status") != "available":
        reason = observation.get("reason_code")
        code = reason if isinstance(reason, str) else "CAPACITY-OBSERVABILITY-GAP"
        raise RuntimeViolation(code, "runtime observation is unavailable")
    authority = _mapping(observation.get("authority"))
    backlog = _mapping(observation.get("backlog"))
    resources = _mapping(observation.get("resources"))
    diagnostics = _mapping(observation.get("diagnostics"))
    work = _mapping(backlog.get("work"))
    outbox = _mapping(backlog.get("outbox"))
    effects = _mapping(backlog.get("effects"))
    return RuntimeCapacitySample(
        offset_milliseconds=offset_milliseconds,
        observed_at=_text(observation.get("observed_at")),
        runtime_state=_text(runtime.get("runtime_state")),
        readiness=_text(runtime.get("readiness")),
        active_runtime_count=_integer(authority.get("active_runtime_count")),
        heartbeat_age_seconds=_optional_integer(authority.get("heartbeat_age_seconds")),
        work_open=_open_count(work, ("ready", "leased")),
        work_oldest_open_age_seconds=_optional_integer(
            work.get("oldest_open_age_seconds")
        ),
        outbox_open=_open_count(outbox, ("ready", "claimed")),
        outbox_oldest_open_age_seconds=_optional_integer(
            outbox.get("oldest_open_age_seconds")
        ),
        effects_open=_open_count(
            effects,
            ("registered", "dispatching", "unknown"),
        ),
        effects_oldest_open_age_seconds=_optional_integer(
            effects.get("oldest_open_age_seconds")
        ),
        process_rss_bytes=_optional_integer(resources.get("process_rss_bytes")),
        process_cpu_milliseconds=_integer(resources.get("process_cpu_milliseconds")),
        process_uptime_seconds=_integer(resources.get("process_uptime_seconds")),
        database_bytes=_integer(resources.get("database_bytes")),
        artifact_bytes=_integer(resources.get("artifact_bytes")),
        disk_free_bytes=_integer(resources.get("disk_free_bytes")),
        disk_state=_text(resources.get("disk_state")),
        diagnostic_retained_bytes=_integer(diagnostics.get("retained_bytes")),
    )


def _issues(
    samples: list[RuntimeCapacitySample],
    *,
    unavailable: list[str],
    max_rss_growth_bytes: int,
    max_backlog_growth: int,
    max_open_backlog_age_seconds: int,
    max_log_growth_bytes: int,
) -> tuple[str, ...]:
    first = samples[0]
    last = samples[-1]
    issues: set[str] = set()
    if unavailable:
        issues.add("CAPACITY-OBSERVABILITY-GAP")
    if any(sample.readiness != "ready" for sample in samples):
        issues.add("CAPACITY-RUNTIME-NOT-READY")
    if any(sample.active_runtime_count != 1 for sample in samples):
        issues.add("CAPACITY-AUTHORITY-COUNT")
    disk_states = {sample.disk_state for sample in samples}
    if "critical" in disk_states:
        issues.add("CAPACITY-DISK-CRITICAL")
    elif "warning" in disk_states:
        issues.add("CAPACITY-DISK-WARNING")
    rss_growth = _optional_delta(first.process_rss_bytes, last.process_rss_bytes)
    if rss_growth is not None and rss_growth > max_rss_growth_bytes:
        issues.add("CAPACITY-RSS-GROWTH")
    if last.open_backlog - first.open_backlog > max_backlog_growth:
        issues.add("CAPACITY-BACKLOG-GROWTH")
    oldest_open_age = _optional_max(
        age
        for sample in samples
        for age in (
            sample.work_oldest_open_age_seconds,
            sample.outbox_oldest_open_age_seconds,
            sample.effects_oldest_open_age_seconds,
        )
    )
    if oldest_open_age is not None and oldest_open_age > max_open_backlog_age_seconds:
        issues.add("CAPACITY-BACKLOG-AGE")
    if (
        last.diagnostic_retained_bytes - first.diagnostic_retained_bytes
        > max_log_growth_bytes
    ):
        issues.add("CAPACITY-LOG-GROWTH")
    return tuple(sorted(issues))


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeViolation(
            "CAPACITY-OBSERVATION-SHAPE",
            "runtime observation shape is invalid",
        )
    return cast(dict[str, Any], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeViolation(
            "CAPACITY-OBSERVATION-SHAPE",
            "runtime observation shape is invalid",
        )
    return value


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise RuntimeViolation(
            "CAPACITY-OBSERVATION-SHAPE",
            "runtime observation shape is invalid",
        )
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _open_count(value: Mapping[str, Any], states: tuple[str, ...]) -> int:
    counts = _mapping(value.get("counts"))
    return sum(_integer(counts.get(state, 0)) for state in states)


def _optional_delta(first: int | None, last: int | None) -> int | None:
    if first is None or last is None:
        return None
    return last - first


def _optional_max(values: Iterable[int | None]) -> int | None:
    present = tuple(value for value in values if value is not None)
    return max(present) if present else None


__all__ = (
    "RuntimeCapacityReport",
    "RuntimeCapacitySample",
    "run_runtime_capacity_baseline",
)
