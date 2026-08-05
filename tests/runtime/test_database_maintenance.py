from __future__ import annotations

import unittest
from uuid import uuid4, uuid7

from armi_runtime.adapters.database_errors import DatabaseViolation
from armi_runtime.adapters.persistence.database_maintenance import (
    DatabaseMaintenanceReport,
    PostgreSQLDatabaseMaintenance,
)


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_report_exposes_only_bounded_operator_result(self) -> None:
        report = DatabaseMaintenanceReport(
            table_count=42,
            completed_at="2026-08-05T10:00:00.000000Z",
        )

        self.assertEqual(
            report.safe_view(),
            {
                "schema_version": "armi.database-maintenance.v1",
                "status": "applied",
                "table_count": 42,
                "completed_at": "2026-08-05T10:00:00.000000Z",
            },
        )

    def test_rejects_invalid_declaration_before_connecting(self) -> None:
        driver = PostgreSQLDatabaseMaintenance()

        for environment_id, statement_timeout, lock_timeout in (
            (uuid4(), 300, 5),
            (uuid7(), 0, 5),
            (uuid7(), 300, 0),
        ):
            with self.subTest(
                environment_id=environment_id,
                statement_timeout=statement_timeout,
                lock_timeout=lock_timeout,
            ):
                with self.assertRaises(DatabaseViolation) as captured:
                    driver.run(
                        "postgresql://must-not-connect",
                        environment_id=environment_id,
                        statement_timeout_seconds=statement_timeout,
                        lock_timeout_seconds=lock_timeout,
                    )

                self.assertEqual(captured.exception.code, "DB-MAINTENANCE-FAILED")


if __name__ == "__main__":
    unittest.main()
