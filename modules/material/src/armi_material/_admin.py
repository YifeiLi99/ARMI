"""Synchronous private observation owned by the life-material module."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from armi_artifact_store import parse_life_material_artifact
from armi_artifact_store.api import ArtifactAdminPort
from armi_kernel.application import (
    ArtifactViolation,
)
from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import (
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialAdminItem,
    MaterialAdminSnapshot,
    MaterialViolation,
)


class PostgreSQLMaterialAdminRead:
    """Read the bounded private material projection through an Admin role."""

    __slots__ = ("_artifacts",)

    def __init__(
        self,
        *,
        artifacts: ArtifactAdminPort,
    ) -> None:
        self._artifacts = artifacts

    def private_snapshot(
        self, transaction: PostgreSQLAdminTransaction, subject_id: UUID
    ) -> MaterialAdminSnapshot:
        rows = self._rows(transaction, subject_id)
        return MaterialAdminSnapshot(
            tuple(self._item(transaction, row) for row in rows[:100]),
            len(rows) > 100,
        )

    def _rows(
        self, transaction: PostgreSQLAdminTransaction, subject_id: UUID
    ) -> list[tuple[object, ...]]:
        return transaction.execute(
            "SELECT material.life_material_id, material.current_revision_id, "
            "material.material_kind, material.head_version, material.created_at, "
            "material.updated_at, material.deleted_at, revision.revision_no, "
            "revision.title, revision.metadata, revision.material_status, "
            "revision.privacy_status, revision.artifact_id "
            "FROM armi.life_materials AS material "
            "JOIN armi.life_material_revisions AS revision "
            "ON revision.life_material_revision_id = material.current_revision_id "
            "WHERE material.subject_id = %s "
            "ORDER BY material.updated_at DESC, material.life_material_id "
            "LIMIT 101",
            (subject_id,),
        ).fetchall()

    def references_artifact(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> bool:
        del transaction, artifact_id
        # The current Admin role has no SELECT grant on material revisions.
        # A concurrent or pre-existing reference is still protected by the FK
        # when Artifact Store performs its catalog CAS delete.
        return False

    def _item(
        self, transaction: PostgreSQLAdminTransaction, row: tuple[object, ...]
    ) -> MaterialAdminItem:
        raw_metadata = row[9]
        if type(raw_metadata) is not dict:
            raise MaterialViolation("MATERIAL-OBSERVATION-SHAPE")
        metadata = cast(dict[object, object], raw_metadata)
        if any(
            type(key) is not str or type(value) is not str
            for key, value in metadata.items()
        ):
            raise MaterialViolation("MATERIAL-OBSERVATION-SHAPE")
        return MaterialAdminItem(
            material_id=UUID(str(row[0])),
            current_revision_id=UUID(str(row[1])),
            material_kind=LifeMaterialKind(str(row[2])),
            head_version=int(cast(int, row[3])),
            revision_no=int(cast(int, row[7])),
            title=str(row[8]),
            body=self._read_body(transaction, UUID(str(row[12]))),
            metadata=tuple(sorted(cast(dict[str, str], raw_metadata).items())),
            material_status=LifeMaterialStatus(str(row[10])),
            privacy_status=LifeMaterialPrivacyStatus(str(row[11])),
            artifact_id=UUID(str(row[12])),
            deleted_at=cast(datetime | None, row[6]),
            created_at=cast(datetime, row[4]),
            updated_at=cast(datetime, row[5]),
        )

    def _read_body(
        self, transaction: PostgreSQLAdminTransaction, artifact_id: UUID
    ) -> str:
        try:
            snapshot = self._artifacts.snapshot(transaction, artifact_id=artifact_id)
            if (
                snapshot is None
                or snapshot.media_type != "application/json"
                or not 1 <= snapshot.byte_size <= 131_072
                or snapshot.logical_kind != "life.material.content"
                or snapshot.privacy_scope.value != "private"
                or snapshot.integrity_status.value != "verified"
            ):
                raise ValueError
            return parse_life_material_artifact(
                self._artifacts.read_verified_bytes(snapshot)
            ).decode("utf-8", errors="strict")
        except ArtifactViolation, UnicodeError, ValueError:
            raise MaterialViolation("MATERIAL-OBSERVATION-ARTIFACT") from None


__all__ = ("PostgreSQLMaterialAdminRead",)
