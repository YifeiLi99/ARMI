"""Synchronous private observation owned by the life-material module."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
from armi_artifact_store import (
    ContentAddressedArtifactStore,
    parse_life_material_artifact,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_kernel.contracts import Digest
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from .api import (
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialAdminItem,
    MaterialAdminSnapshot,
    MaterialViolation,
)

_SEARCH_PATH = "pg_catalog, armi"
_POOL_OPEN_TIMEOUT_SECONDS = 5.0


class PostgreSQLMaterialAdminRead:
    """Read the bounded private material projection through an Admin role."""

    __slots__ = ("_conninfo", "_expected_role", "_storage")

    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        artifact_root: Path,
        max_object_bytes: int,
    ) -> None:
        if not expected_role.startswith("armi_") or not expected_role.endswith(
            "_admin"
        ):
            raise ValueError("expected_role must be an environment Admin login")
        self._conninfo = conninfo
        self._expected_role = expected_role
        self._storage = ContentAddressedArtifactStore(
            artifact_root,
            max_object_bytes=max_object_bytes,
        )

    def private_snapshot(self, subject_id: UUID) -> MaterialAdminSnapshot:
        rows = self._rows(subject_id)
        return MaterialAdminSnapshot(
            tuple(self._item(row) for row in rows[:100]),
            len(rows) > 100,
        )

    def _rows(self, subject_id: UUID) -> list[tuple[Any, ...]]:
        pool = ConnectionPool(
            self._conninfo,
            min_size=0,
            max_size=1,
            open=False,
            configure=self._configure,
            reset=self._reset,
            kwargs={"application_name": "armi-material-admin-observation"},
        )
        try:
            pool.open(wait=True, timeout=_POOL_OPEN_TIMEOUT_SECONDS)
            with pool.connection() as connection:
                self._verify(connection)
                connection.execute("SET TRANSACTION READ ONLY")
                return connection.execute(
                    "SELECT material.life_material_id, material.current_revision_id, "
                    "material.material_kind, material.head_version, material.created_at, "
                    "material.updated_at, material.deleted_at, revision.revision_no, "
                    "revision.title, revision.metadata, revision.material_status, "
                    "revision.privacy_status, artifact.artifact_id, "
                    "artifact.content_digest, artifact.media_type, artifact.byte_size, "
                    "artifact.logical_kind, artifact.privacy_scope, artifact.integrity_status "
                    "FROM armi.life_materials AS material "
                    "JOIN armi.life_material_revisions AS revision "
                    "ON revision.life_material_revision_id = material.current_revision_id "
                    "JOIN armi.artifacts AS artifact "
                    "ON artifact.artifact_id = revision.artifact_id "
                    "WHERE material.subject_id = %s "
                    "ORDER BY material.updated_at DESC, material.life_material_id "
                    "LIMIT 101",
                    (subject_id,),
                ).fetchall()
        finally:
            pool.close()

    def _item(self, row: tuple[Any, ...]) -> MaterialAdminItem:
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
            head_version=int(row[3]),
            revision_no=int(row[7]),
            title=str(row[8]),
            body=self._read_body(row),
            metadata=tuple(sorted(cast(dict[str, str], raw_metadata).items())),
            material_status=LifeMaterialStatus(str(row[10])),
            privacy_status=LifeMaterialPrivacyStatus(str(row[11])),
            artifact_id=UUID(str(row[12])),
            deleted_at=row[6],
            created_at=row[4],
            updated_at=row[5],
        )

    def _read_body(self, row: tuple[Any, ...]) -> str:
        try:
            if (
                str(row[14]) != "application/json"
                or type(row[15]) is not int
                or not 1 <= row[15] <= 131_072
                or str(row[16]) != "life.material.content"
                or str(row[17]) != "private"
                or str(row[18]) != "verified"
            ):
                raise ValueError
            ref = ArtifactRef(
                artifact_id=ArtifactId(UUID(str(row[12]))),
                content_digest=Digest(str(row[13])),
                byte_size=row[15],
                media_type=str(row[14]),
                logical_kind=str(row[16]),
                privacy_scope=ArtifactPrivacyScope(str(row[17])),
                integrity_status=ArtifactIntegrityStatus(str(row[18])),
            )
            return parse_life_material_artifact(
                self._storage.read_verified_bytes(ref)
            ).decode("utf-8", errors="strict")
        except ArtifactViolation, UnicodeError, ValueError:
            raise MaterialViolation("MATERIAL-OBSERVATION-ARTIFACT") from None

    def _configure(self, connection: psycopg.Connection[Any]) -> None:
        connection.execute("SET search_path TO pg_catalog, armi")
        self._verify(connection)
        connection.commit()

    def _reset(self, connection: psycopg.Connection[Any]) -> None:
        if connection.info.transaction_status != TransactionStatus.IDLE:
            connection.rollback()
        connection.execute("RESET ROLE")
        connection.execute("RESET ALL")
        connection.execute("SET search_path TO pg_catalog, armi")
        self._verify(connection)
        connection.commit()

    def _verify(self, connection: psycopg.Connection[Any]) -> None:
        row = connection.execute(
            "SELECT session_user, current_user, current_setting('search_path')"
        ).fetchone()
        if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
            raise MaterialViolation("MATERIAL-OBSERVATION-ROLE")


__all__ = ("PostgreSQLMaterialAdminRead",)
