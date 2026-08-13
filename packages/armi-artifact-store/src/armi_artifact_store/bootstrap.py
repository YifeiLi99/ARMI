"""Composition entry for the artifact catalog owner."""

from pathlib import Path

from ._admin import PostgreSQLArtifactAdmin
from ._postgresql import PostgreSQLArtifactCatalog
from .api import ArtifactAdminPort, ArtifactCatalogPort


def bootstrap_artifact_catalog() -> ArtifactCatalogPort:
    return PostgreSQLArtifactCatalog()


def bootstrap_artifact_admin(
    *, artifact_root: Path, max_object_bytes: int = 104_857_600
) -> ArtifactAdminPort:
    return PostgreSQLArtifactAdmin(
        artifact_root=artifact_root, max_object_bytes=max_object_bytes
    )


__all__ = ("bootstrap_artifact_admin", "bootstrap_artifact_catalog")
