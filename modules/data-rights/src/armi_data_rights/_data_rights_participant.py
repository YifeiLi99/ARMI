"""Data-rights owner contribution for its own ledger tables."""

from __future__ import annotations

from typing import LiteralString

from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsTupleRecordStream,
)

_OWNER = DataRightsOwnerIdentity("data-rights")
_VERSION = DataRightsContributionVersion(1)
_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "creator_exports",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.creator_exports AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "deletion_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.deletion_items AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "deletion_orders",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.deletion_orders AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class PostgreSQLDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _OWNER

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return _VERSION

    async def discover(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsDiscoveryRequest,
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(_OWNER)

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        del transaction, request
        return DataRightsApplyContribution(_OWNER)

    async def export(
        self,
        transaction: PostgreSQLTransaction,
        scope: DataRightsExportScope,
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        result: list[DataRightsExportSegment] = []
        for name, statement in _SEGMENTS:
            rows = await (await transaction.execute(statement)).fetchall()
            records = tuple(DataRightsCanonicalRecord(bytes(row[0])) for row in rows)
            result.append(
                DataRightsExportSegment(
                    _OWNER,
                    _VERSION,
                    name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(result)


__all__ = ("PostgreSQLDataRightsParticipant",)
