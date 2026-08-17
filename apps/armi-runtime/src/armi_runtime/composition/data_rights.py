"""Fixed Data Rights participant roster for the single active Runtime."""

from __future__ import annotations

from typing import LiteralString

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_data_rights.api import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsParticipant,
    DataRightsParticipantViolation,
    DataRightsTupleRecordStream,
)
from armi_runtime_foundation import PostgreSQLTransaction

_RUNTIME_OWNER = DataRightsOwnerIdentity("runtime")
_ARTIFACT_OWNER = DataRightsOwnerIdentity("artifact-store")
_VERSION = DataRightsContributionVersion(1)
_RUNTIME_SEGMENTS: tuple[tuple[str, LiteralString], ...] = (
    (
        "audit_events",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.audit_events AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "deployment_environments",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.deployment_environments AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "durable_work",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.durable_work AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "life_generations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.life_generations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "runtime_bundle_activations",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.runtime_bundle_activations AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "runtime_instances",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.runtime_instances AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "runtime_recovery_metrics",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.runtime_recovery_metrics AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "runtime_recovery_runs",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.runtime_recovery_runs AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "subject_commits",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.subject_commits AS source ORDER BY to_jsonb(source)::text""",
    ),
    (
        "subjects",
        """SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.subjects AS source ORDER BY to_jsonb(source)::text""",
    ),
)


class RuntimeDataRightsParticipant:
    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _RUNTIME_OWNER

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return _VERSION

    async def discover(
        self, transaction: PostgreSQLTransaction, request: DataRightsDiscoveryRequest
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(_RUNTIME_OWNER)

    async def apply(
        self, transaction: PostgreSQLTransaction, request: DataRightsApplyRequest
    ) -> DataRightsApplyContribution:
        await transaction.execute(
            """UPDATE armi.subjects SET state_epoch = state_epoch + 1
               WHERE singleton_key = 1"""
        )
        del request
        return DataRightsApplyContribution(_RUNTIME_OWNER)

    async def export(
        self, transaction: PostgreSQLTransaction, scope: DataRightsExportScope
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        result: list[DataRightsExportSegment] = []
        for name, statement in _RUNTIME_SEGMENTS:
            rows = await (await transaction.execute(statement)).fetchall()
            records = tuple(DataRightsCanonicalRecord(bytes(row[0])) for row in rows)
            result.append(
                DataRightsExportSegment(
                    _RUNTIME_OWNER,
                    _VERSION,
                    name,
                    "application/x-ndjson",
                    DataRightsTupleRecordStream(records),
                )
            )
        return tuple(result)


class ArtifactStoreDataRightsParticipant:
    __slots__ = ("_catalog",)

    def __init__(self, catalog: ArtifactCatalogPort) -> None:
        self._catalog = catalog

    @property
    def owner_identity(self) -> DataRightsOwnerIdentity:
        return _ARTIFACT_OWNER

    @property
    def schema_version(self) -> DataRightsContributionVersion:
        return _VERSION

    async def discover(
        self, transaction: PostgreSQLTransaction, request: DataRightsDiscoveryRequest
    ) -> DataRightsDiscoveryContribution:
        del transaction, request
        return DataRightsDiscoveryContribution(_ARTIFACT_OWNER)

    async def apply(
        self, transaction: PostgreSQLTransaction, request: DataRightsApplyRequest
    ) -> DataRightsApplyContribution:
        del transaction, request
        return DataRightsApplyContribution(_ARTIFACT_OWNER)

    async def export(
        self, transaction: PostgreSQLTransaction, scope: DataRightsExportScope
    ) -> tuple[DataRightsExportSegment, ...]:
        del scope
        refs = await self._catalog.all_refs_in(transaction)
        records = tuple(
            DataRightsCanonicalRecord(
                rfc8785.dumps(
                    {
                        "artifact_id": str(ref.artifact_id.value),
                        "content_digest": ref.content_digest.value,
                        "byte_size": ref.byte_size,
                        "media_type": ref.media_type,
                        "logical_kind": ref.logical_kind,
                        "privacy_scope": ref.privacy_scope.value,
                        "integrity_status": ref.integrity_status.value,
                    }
                )
                + b"\n"
            )
            for ref in refs
        )
        return (
            DataRightsExportSegment(
                _ARTIFACT_OWNER,
                _VERSION,
                "artifacts",
                "application/x-ndjson",
                DataRightsTupleRecordStream(records),
                tuple(refs),
            ),
        )


def compose_data_rights_participants(
    *,
    business: tuple[DataRightsParticipant, ...],
    catalog: ArtifactCatalogPort,
) -> tuple[DataRightsParticipant, ...]:
    participants: tuple[DataRightsParticipant, ...] = (
        *business,
        RuntimeDataRightsParticipant(),
        ArtifactStoreDataRightsParticipant(catalog),
    )
    identities = tuple(item.owner_identity.value for item in participants)
    expected = (
        "interaction",
        "perception",
        "evidence",
        "opportunity",
        "experience",
        "cognition",
        "memory",
        "relationship",
        "activity",
        "material",
        "subject-state",
        "mood",
        "prompt",
        "sleep",
        "expression",
        "capability",
        "effect",
        "web-observation",
        "codex",
        "context",
        "data-rights",
        "runtime",
        "artifact-store",
    )
    if identities != expected or len(set(identities)) != len(identities):
        raise DataRightsParticipantViolation("DATA-RIGHTS-PARTICIPANT-ROSTER")
    return participants


__all__ = ("compose_data_rights_participants",)
