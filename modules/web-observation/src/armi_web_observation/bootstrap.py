"""Web observation module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_evidence.api import EvidenceWritePort
from armi_kernel.application import CredentialLocator, CredentialPort, DurableWorkPort
from armi_opportunity.api import OpportunityAdmissionPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLWebObservationAdmin
from ._application import WebSearchPipeline
from ._commit import PostgreSQLWebResearchCommit
from ._context_postgresql import PostgreSQLWebContextRead
from ._recovery import WebObservationRecoveryParticipant
from ._research import WebResearchAdmissionPipeline
from .api import (
    WebArtifactCatalogPort,
    WebArtifactStorePort,
    WebContextReadPort,
    WebObservationAdminPort,
    WebObservationRuntimePort,
    WebResearchCommitPort,
    WebResearchRuntimePort,
)


def bootstrap_web_observation_admin() -> WebObservationAdminPort:
    return PostgreSQLWebObservationAdmin()


Diagnostic = Callable[[str], None]


def bootstrap_web_research_commit() -> WebResearchCommitPort:
    return PostgreSQLWebResearchCommit()


def bootstrap_web_context_read() -> WebContextReadPort:
    return PostgreSQLWebContextRead()


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
    opportunity: OpportunityAdmissionPort,
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
        opportunity=opportunity,
        diagnostic=diagnostic,
    )


def bootstrap_web_research(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: WebArtifactStorePort,
    work: DurableWorkPort,
    custody: WebObservationRuntimePort,
    evidence: EvidenceWritePort,
    opportunity: OpportunityAdmissionPort,
    diagnostic: Diagnostic | None = None,
) -> WebResearchRuntimePort:
    return WebResearchAdmissionPipeline(
        factory=factory,
        storage=storage,
        work=work,
        custody=custody,
        evidence=evidence,
        opportunity=opportunity,
        diagnostic=diagnostic,
    )


def bootstrap_web_observation_recovery() -> RecoveryParticipant:
    return WebObservationRecoveryParticipant()


__all__ = (
    "bootstrap_web_context_read",
    "bootstrap_web_observation",
    "bootstrap_web_observation_admin",
    "bootstrap_web_observation_recovery",
    "bootstrap_web_research",
    "bootstrap_web_research_commit",
)
