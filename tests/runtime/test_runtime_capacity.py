from __future__ import annotations

import unittest
from typing import Any, cast

from armi_runtime.composition.runtime_capacity import run_runtime_capacity_baseline
from armi_runtime.composition.runtime_errors import RuntimeViolation


class _Clock:
    def __init__(self) -> None:
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


def _status(
    *,
    rss: int,
    cpu: int,
    work_ready: int = 0,
    work_age_seconds: int = 2,
    retained: int = 100,
    disk_state: str = "ok",
) -> dict[str, Any]:
    return {
        "status": "running",
        "pid": 1234,
        "runtime": {
            "runtime_state": "degraded",
            "readiness": "ready",
            "reason_codes": ["RUNTIME_MODEL_UNAVAILABLE"],
            "observability": {
                "schema_version": "armi.runtime-observability.v1",
                "status": "available",
                "observed_at": "2026-08-05T10:00:00.000000Z",
                "authority": {
                    "active_runtime_count": 1,
                    "heartbeat_age_seconds": 1,
                },
                "backlog": {
                    "work": {
                        "counts": {"ready": work_ready, "completed": 4},
                        "oldest_open_age_seconds": (
                            work_age_seconds if work_ready else None
                        ),
                    },
                    "effects": {
                        "counts": {"completed": 3},
                        "oldest_open_age_seconds": None,
                    },
                },
                "resources": {
                    "process_rss_bytes": rss,
                    "process_cpu_milliseconds": cpu,
                    "process_uptime_seconds": 20,
                    "database_bytes": 8_192,
                    "artifact_bytes": 4_096,
                    "artifact_counts": {"verified": 4},
                    "disk_total_bytes": 1_000_000,
                    "disk_free_bytes": 800_000,
                    "disk_state": disk_state,
                },
                "diagnostics": {
                    "sink": "file",
                    "current_bytes": retained,
                    "retained_bytes": retained,
                    "rotations": 0,
                    "retention_deleted": 0,
                    "retention_failures": 0,
                },
            },
        },
    }


class RuntimeCapacityBaselineTests(unittest.TestCase):
    def test_reports_bounded_samples_and_deltas(self) -> None:
        clock = _Clock()
        statuses = iter(
            (
                _status(rss=1000, cpu=10),
                _status(rss=1200, cpu=20),
                _status(rss=1400, cpu=35),
            )
        )

        report = run_runtime_capacity_baseline(
            lambda: next(statuses),
            duration_seconds=2,
            sample_interval_seconds=1,
            max_rss_growth_bytes=1000,
            max_backlog_growth=0,
            max_open_backlog_age_seconds=10,
            max_log_growth_bytes=1000,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        view = report.safe_view()
        deltas = cast(dict[str, Any], view["deltas"])
        samples = cast(list[dict[str, Any]], view["samples"])

        self.assertEqual(report.status, "pass")
        self.assertEqual(view["sample_count"], 3)
        self.assertEqual(deltas["process_rss_bytes"], 400)
        self.assertEqual(deltas["process_cpu_milliseconds"], 25)
        self.assertEqual(
            [sample["offset_milliseconds"] for sample in samples],
            [0, 1000, 2000],
        )

    def test_marks_growth_gaps_and_disk_pressure_for_attention(self) -> None:
        clock = _Clock()
        statuses = iter(
            (
                {
                    "status": "running",
                    "runtime": {
                        "runtime_state": "degraded",
                        "readiness": "ready",
                        "observability": {
                            "status": "unavailable",
                            "reason_code": "OBSERVABILITY_NOT_SAMPLED",
                        },
                    },
                },
                _status(rss=1000, cpu=10),
                _status(
                    rss=3000,
                    cpu=20,
                    work_ready=3,
                    work_age_seconds=20,
                    retained=400,
                    disk_state="warning",
                ),
            )
        )

        report = run_runtime_capacity_baseline(
            lambda: next(statuses),
            duration_seconds=2,
            sample_interval_seconds=1,
            max_rss_growth_bytes=100,
            max_backlog_growth=1,
            max_open_backlog_age_seconds=10,
            max_log_growth_bytes=100,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        self.assertEqual(report.status, "attention")
        self.assertEqual(
            report.issue_codes,
            (
                "CAPACITY-BACKLOG-AGE",
                "CAPACITY-BACKLOG-GROWTH",
                "CAPACITY-DISK-WARNING",
                "CAPACITY-LOG-GROWTH",
                "CAPACITY-OBSERVABILITY-GAP",
                "CAPACITY-RSS-GROWTH",
            ),
        )
        self.assertEqual(report.unavailable_reasons, ("OBSERVABILITY_NOT_SAMPLED",))

    def test_rejects_invalid_declaration_and_no_usable_sample(self) -> None:
        clock = _Clock()
        with self.assertRaises(RuntimeViolation) as invalid:
            run_runtime_capacity_baseline(
                lambda: {},
                duration_seconds=0,
                sample_interval_seconds=1,
                max_rss_growth_bytes=0,
                max_backlog_growth=0,
                max_open_backlog_age_seconds=10,
                max_log_growth_bytes=0,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        self.assertEqual(invalid.exception.code, "CAPACITY-DECLARATION")

        with self.assertRaises(RuntimeViolation) as unavailable:
            run_runtime_capacity_baseline(
                lambda: {"status": "stopped"},
                duration_seconds=1,
                sample_interval_seconds=1,
                max_rss_growth_bytes=0,
                max_backlog_growth=0,
                max_open_backlog_age_seconds=10,
                max_log_growth_bytes=0,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        self.assertEqual(
            unavailable.exception.code,
            "CAPACITY-OBSERVABILITY-UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
