from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from armi_runtime.adapters.persistence.runtime_observability import (
    DatabaseObservation,
    RuntimeObservationError,
)
from armi_runtime.composition.diagnostics import DiagnosticSinkStatus
from armi_runtime.composition.runtime_observability import RuntimeObservationDriver


class _ObservationPort:
    def __init__(self, observation: DatabaseObservation) -> None:
        self.observation = observation
        self.fail = False
        self.closed = False

    async def open(self) -> None:
        return None

    async def collect(self) -> DatabaseObservation:
        if self.fail:
            raise RuntimeObservationError("OBSERVABILITY_DATABASE_UNAVAILABLE")
        return self.observation

    async def close(self) -> None:
        self.closed = True


def _database_observation() -> DatabaseObservation:
    return DatabaseObservation(
        work_counts=(("completed", 3), ("ready", 2)),
        work_oldest_open_seconds=7,
        effect_counts=(("completed", 1), ("unknown", 1)),
        effect_oldest_open_seconds=9,
        active_runtime_count=1,
        runtime_heartbeat_age_seconds=2,
        artifact_counts=(("verified", 4),),
        artifact_bytes=4096,
        database_bytes=8192,
    )


class RuntimeObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_safe_backlog_resource_and_log_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            port = _ObservationPort(_database_observation())
            driver = RuntimeObservationDriver(
                port,
                data_root=Path(temporary).resolve(),
                sample_interval_seconds=10,
                disk_warning_free_bytes=2,
                disk_critical_free_bytes=1,
                diagnostic_status=lambda: DiagnosticSinkStatus(
                    mode="file",
                    reason_code=None,
                    current_bytes=256,
                    retained_bytes=512,
                    rotations=2,
                    retention_deleted=1,
                    retention_failures=0,
                ),
            )
            await driver.collect_once()
            snapshot = driver.snapshot()
            await driver.close()

        self.assertEqual(snapshot["status"], "available")
        authority = cast(dict[str, Any], snapshot["authority"])
        backlog = cast(dict[str, Any], snapshot["backlog"])
        resources = cast(dict[str, Any], snapshot["resources"])
        diagnostics = cast(dict[str, Any], snapshot["diagnostics"])
        self.assertEqual(authority["active_runtime_count"], 1)
        self.assertEqual(backlog["work"]["counts"]["ready"], 2)
        self.assertNotIn("outbox", backlog)
        self.assertEqual(backlog["effects"]["oldest_open_age_seconds"], 9)
        self.assertEqual(resources["artifact_bytes"], 4096)
        self.assertEqual(resources["disk_state"], "ok")
        self.assertEqual(diagnostics["retained_bytes"], 512)
        self.assertTrue(port.closed)

    async def test_sampling_failure_is_explicit_and_does_not_reuse_stale_values(
        self,
    ) -> None:
        signals: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            port = _ObservationPort(_database_observation())
            driver = RuntimeObservationDriver(
                port,
                data_root=Path(temporary).resolve(),
                sample_interval_seconds=10,
                disk_warning_free_bytes=2,
                disk_critical_free_bytes=1,
                diagnostic_status=lambda: DiagnosticSinkStatus(
                    mode="stderr",
                    reason_code="RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE",
                    current_bytes=0,
                    retained_bytes=0,
                    rotations=0,
                    retention_deleted=0,
                    retention_failures=0,
                ),
                diagnostic=signals.append,
            )
            await driver.collect_once()
            port.fail = True
            await driver.collect_once()
            await driver.collect_once()
            snapshot = driver.snapshot()

        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["reason_code"], "OBSERVABILITY_SAMPLE_UNAVAILABLE")
        self.assertNotIn("backlog", snapshot)
        self.assertEqual(signals, ["runtime.observability.unavailable"])


if __name__ == "__main__":
    unittest.main()
