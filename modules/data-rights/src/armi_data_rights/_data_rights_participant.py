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
    DataRightsRelatedRef,
    DataRightsTargetRef,
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
        "data_rights_party_fences",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.data_rights_party_fences AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "data_rights_identity_keys",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.data_rights_identity_keys AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "data_rights_order_items",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.data_rights_order_items AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "data_rights_order_retry_attempts",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.data_rights_order_retry_attempts AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "data_rights_orders",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.data_rights_orders AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "managed_data_snapshot_parties",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.managed_data_snapshot_parties AS source
           ORDER BY to_jsonb(source)::text""",
    ),
    (
        "managed_data_snapshots",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8')
           FROM armi.managed_data_snapshots AS source
           ORDER BY to_jsonb(source)::text""",
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
        rows = await (
            await transaction.execute(
                """SELECT snapshot.managed_snapshot_id
                   FROM armi.managed_data_snapshots AS snapshot
                   JOIN armi.managed_data_snapshot_parties AS scope
                     ON scope.managed_snapshot_id=snapshot.managed_snapshot_id
                   WHERE scope.party_id=%s AND snapshot.status='active'
                   ORDER BY snapshot.managed_snapshot_id""",
                (request.party_id,),
            )
        ).fetchall()
        return DataRightsDiscoveryContribution(
            _OWNER,
            related_refs=tuple(
                DataRightsRelatedRef("managed-snapshot", row[0]) for row in rows
            ),
            targets=tuple(
                DataRightsTargetRef(
                    "managed_snapshot",
                    row[0],
                    "operator_remove",
                    "operator_managed_snapshot",
                )
                for row in rows
            ),
        )

    async def apply(
        self,
        transaction: PostgreSQLTransaction,
        request: DataRightsApplyRequest,
    ) -> DataRightsApplyContribution:
        del transaction
        return DataRightsApplyContribution(
            _OWNER,
            tuple(
                target
                for target in request.targets
                if target.responsible_owner == _OWNER.value
            ),
        )

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
