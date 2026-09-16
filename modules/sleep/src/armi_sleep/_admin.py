"""Sleep-owned management observations, without maintenance mutation."""

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLSleepAdminRead:
    def has_active_maintenance(self, transaction: PostgreSQLAdminTransaction) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.maintenance_sessions WHERE finished_at IS NULL)"
        ).fetchone()
        return row is not None and bool(row[0])
