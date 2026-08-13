"""Composition entry for the artifact catalog owner."""

from ._postgresql import PostgreSQLArtifactCatalog
from .api import ArtifactCatalogPort


def bootstrap_artifact_catalog() -> ArtifactCatalogPort:
    return PostgreSQLArtifactCatalog()


__all__ = ("bootstrap_artifact_catalog",)
