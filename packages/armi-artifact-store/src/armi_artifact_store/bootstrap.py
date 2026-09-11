"""Composition entry for the artifact catalog owner."""

from pathlib import Path

from armi_kernel.application import DurableWorkPort
from armi_runtime_foundation import (
    PostgreSQLAdminUnitOfWorkFactory,
    PostgreSQLRuntimeUnitOfWorkFactory,
)

from ._admin import PostgreSQLArtifactAdmin
from ._admin_content import PostgreSQLArtifactAdminContent
from ._lifecycle import ArtifactLifecycleCoordinator
from ._postgresql import PostgreSQLArtifactCatalog
from .api import (
    ArtifactAdminContentPort,
    ArtifactAdminPort,
    ArtifactCatalogPort,
    ArtifactLifecyclePort,
)
from .content_store import ContentAddressedArtifactStore


def bootstrap_artifact_catalog() -> ArtifactCatalogPort:
    return PostgreSQLArtifactCatalog()


def bootstrap_artifact_admin_content(
    *, artifact_root: Path, factory: PostgreSQLAdminUnitOfWorkFactory
) -> ArtifactAdminContentPort:
    return PostgreSQLArtifactAdminContent(artifact_root, factory)


def bootstrap_artifact_admin(
    *, artifact_root: Path, max_object_bytes: int = 104_857_600
) -> ArtifactAdminPort:
    return PostgreSQLArtifactAdmin(
        artifact_root=artifact_root, max_object_bytes=max_object_bytes
    )


def bootstrap_artifact_lifecycle(
    storage: ContentAddressedArtifactStore,
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    durable_work: DurableWorkPort,
) -> ArtifactLifecyclePort:
    return ArtifactLifecycleCoordinator(storage, unit_of_work_factory, durable_work)


__all__ = (
    "bootstrap_artifact_admin",
    "bootstrap_artifact_admin_content",
    "bootstrap_artifact_catalog",
    "bootstrap_artifact_lifecycle",
)
