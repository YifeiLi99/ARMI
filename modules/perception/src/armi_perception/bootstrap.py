"""Perception module composition entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_data_rights.api import DataRightsParticipant
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_interaction.api import ExternalMessagePartKind, InteractionPerceptionPort
from armi_opportunity.api import OpportunityAdmissionPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLPerceptionAdmin
from ._application import Diagnostic, ExternalContentPipeline
from ._data_rights import PostgreSQLPerceptionDataRightsParticipant
from ._recognizer import ExternalContentRecognizer
from ._recovery import PerceptionRecoveryParticipant
from .api import (
    ExternalContentRecognitionPort,
    ExternalMediaFetchPort,
    PerceptionAdminPort,
    PerceptionArtifactCatalogPort,
    PerceptionDurableWorkPort,
    PerceptionWakeupPort,
    PerceptionWorkerPort,
)


def bootstrap_perception_admin() -> PerceptionAdminPort:
    return PostgreSQLPerceptionAdmin()


compose_external_content_pipeline = ExternalContentPipeline


@dataclass(frozen=True, slots=True)
class PerceptionModule:
    worker: PerceptionWorkerPort

    async def open(self) -> None:
        await self.worker.open()

    async def close(self) -> None:
        await self.worker.close()

    def stop(self) -> None:
        self.worker.stop()


def bootstrap_perception(
    *,
    unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: ContentAddressedArtifactStore,
    catalog: PerceptionArtifactCatalogPort,
    work: PerceptionDurableWorkPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    interaction: InteractionPerceptionPort,
    opportunity: OpportunityAdmissionPort,
    fetch: ExternalMediaFetchPort,
    ark_recognizer: ExternalContentRecognitionPort,
    speech_recognizer: ExternalContentRecognitionPort,
    target_for: Callable[[ExternalMessagePartKind], tuple[str, str]],
    wakeups: PerceptionWakeupPort,
    diagnostic: Diagnostic | None = None,
) -> PerceptionModule:
    recognizer = ExternalContentRecognizer(
        ark=ark_recognizer,
        speech=speech_recognizer,
    )
    worker = ExternalContentPipeline(
        factory=unit_of_work_factory,
        storage=storage,
        catalog=catalog,
        work=work,
        evidence=evidence,
        evidence_read=evidence_read,
        interaction=interaction,
        opportunity=opportunity,
        fetch=fetch,
        recognizer=recognizer,
        target_for=target_for,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )
    return PerceptionModule(worker)


def bootstrap_perception_data_rights() -> DataRightsParticipant:
    return PostgreSQLPerceptionDataRightsParticipant()


def bootstrap_perception_recovery() -> RecoveryParticipant:
    return PerceptionRecoveryParticipant()


__all__ = (
    "PerceptionModule",
    "bootstrap_perception",
    "bootstrap_perception_admin",
    "bootstrap_perception_data_rights",
    "bootstrap_perception_recovery",
    "compose_external_content_pipeline",
)
