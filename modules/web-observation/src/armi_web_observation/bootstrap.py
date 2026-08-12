"""Web observation module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_evidence.api import EvidenceWritePort
from armi_kernel.application import CredentialLocator, CredentialPort, DurableWorkPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import WebSearchPipeline
from ._commit import PostgreSQLWebResearchCommit
from ._research import WebResearchAdmissionPipeline
from .api import (
    WebArtifactCatalogPort,
    WebArtifactStorePort,
    WebObservationRuntimePort,
    WebResearchCommitPort,
    WebResearchRuntimePort,
)

Diagnostic = Callable[[str], None]


def bootstrap_web_research_commit() -> WebResearchCommitPort:
    return PostgreSQLWebResearchCommit()


def bootstrap_web_observation(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: WebArtifactStorePort,
    catalog: WebArtifactCatalogPort,
    work: DurableWorkPort,
    credential_port: CredentialPort,
    credential_locator: CredentialLocator,
    manifest_bytes: bytes,
    evidence: EvidenceWritePort,
    diagnostic: Diagnostic | None = None,
) -> WebObservationRuntimePort:
    return WebSearchPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        work=work,
        credential_port=credential_port,
        credential_locator=credential_locator,
        manifest_bytes=manifest_bytes,
        evidence=evidence,
        diagnostic=diagnostic,
    )


def bootstrap_web_research(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: WebArtifactStorePort,
    work: DurableWorkPort,
    custody: WebObservationRuntimePort,
    evidence: EvidenceWritePort,
    diagnostic: Diagnostic | None = None,
) -> WebResearchRuntimePort:
    return WebResearchAdmissionPipeline(
        factory=factory,
        storage=storage,
        work=work,
        custody=custody,
        evidence=evidence,
        diagnostic=diagnostic,
    )


__all__ = (
    "bootstrap_web_observation",
    "bootstrap_web_research",
    "bootstrap_web_research_commit",
)
