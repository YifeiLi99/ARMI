"""Life-material module composition entry point."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLMaterialAdminRead
from ._application import MaterialApplication
from ._commit import PostgreSQLMaterialCommit
from ._postgresql import PostgreSQLMaterialOwner
from .api import (
    MaterialAdminReadPort,
    MaterialCognitionPort,
    MaterialCommitPort,
    MaterialProjectionPort,
    MaterialReadPort,
)


@dataclass(frozen=True, slots=True)
class MaterialModule:
    read: MaterialReadPort
    cognition: MaterialCognitionPort
    commit: MaterialCommitPort
    projection: MaterialProjectionPort
    _owner: PostgreSQLMaterialOwner

    async def open(self) -> None:
        await self._owner.open()

    async def close(self) -> None:
        await self._owner.close()


def bootstrap_material(
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    *,
    catalog: ArtifactCatalogPort,
    subject_id: UUID,
    data_root: Path,
    max_object_bytes: int,
) -> MaterialModule:
    application = MaterialApplication()
    owner = PostgreSQLMaterialOwner(
        factory,
        catalog=catalog,
        subject_id=subject_id,
        data_root=data_root,
        max_object_bytes=max_object_bytes,
    )
    return MaterialModule(
        owner, application, PostgreSQLMaterialCommit(application), owner, owner
    )


def bootstrap_material_admin_read(
    conninfo: str,
    *,
    expected_role: str,
    artifact_root: Path,
    max_object_bytes: int = 104_857_600,
) -> MaterialAdminReadPort:
    return PostgreSQLMaterialAdminRead(
        conninfo,
        expected_role=expected_role,
        artifact_root=artifact_root,
        max_object_bytes=max_object_bytes,
    )


def bootstrap_material_cognition() -> MaterialCognitionPort:
    return MaterialApplication()


def bootstrap_material_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("material")


__all__ = (
    "MaterialModule",
    "bootstrap_material",
    "bootstrap_material_admin_read",
    "bootstrap_material_cognition",
    "bootstrap_material_recovery",
)
