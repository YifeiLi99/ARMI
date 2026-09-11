"""Protect in-progress retention work from overlapping content changes."""

from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLDataRightsAdminGuard:
    def content_busy(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.data_rights_orders WHERE execution_status<>'completed') "
            "OR EXISTS(SELECT 1 FROM armi.creator_exports WHERE status IN ('building','published_unsettled'))"
        ).fetchone()
        return row is not None and bool(row[0])


__all__ = ("PostgreSQLDataRightsAdminGuard",)
