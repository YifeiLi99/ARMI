"""Web observation module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_attention.api import OpportunityAdmissionPort
from armi_data_rights.api import DataRightsParticipant
from armi_evidence.api import EvidenceWritePort
from armi_kernel.application import CredentialLocator, CredentialPort, DurableWorkPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLWebObservationAdmin
from ._application import WebSearchPipeline
from ._commit import PostgreSQLWebResearchCommit
from ._context_postgresql import PostgreSQLWebContextRead
from ._custody import normalize_full_response
from ._data_rights import PostgreSQLWebObservationDataRightsParticipant
from ._provider_contract import (
    API_BASE,
    BINDING_ID,
    MODEL,
    TOOL_DECLARATION,
    WebSearchViolation,
    normalize_provider_response,
)
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
normalize_web_observation_response = normalize_full_response
web_search_api_base = API_BASE
web_search_binding_id = BINDING_ID
web_search_model = MODEL
web_search_tool_declaration = TOOL_DECLARATION
normalize_web_search_provider_response = normalize_provider_response
web_search_violation = WebSearchViolation


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
    catalog: WebArtifactCatalogPort,
    work: DurableWorkPort,
    custody: WebObservationRuntimePort,
    evidence: EvidenceWritePort,
    opportunity: OpportunityAdmissionPort,
    diagnostic: Diagnostic | None = None,
) -> WebResearchRuntimePort:
    return WebResearchAdmissionPipeline(
        factory=factory,
        storage=storage,
        catalog=catalog,
        work=work,
        custody=custody,
        evidence=evidence,
        opportunity=opportunity,
        diagnostic=diagnostic,
    )


def bootstrap_web_observation_data_rights() -> DataRightsParticipant:
    return PostgreSQLWebObservationDataRightsParticipant()


def bootstrap_web_observation_recovery() -> RecoveryParticipant:
    return WebObservationRecoveryParticipant()


__all__ = (
    "bootstrap_web_context_read",
    "bootstrap_web_observation",
    "bootstrap_web_observation_admin",
    "bootstrap_web_observation_data_rights",
    "bootstrap_web_observation_recovery",
    "bootstrap_web_research",
    "bootstrap_web_research_commit",
    "normalize_web_observation_response",
    "normalize_web_search_provider_response",
    "web_search_api_base",
    "web_search_binding_id",
    "web_search_model",
    "web_search_tool_declaration",
    "web_search_violation",
)
