"""Perception module composition entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_evidence.api import EvidenceWritePort
from armi_interaction.api import ExternalMessagePartKind
from armi_opportunity.api import OpportunityAdmissionPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import Diagnostic, ExternalContentPipeline
from ._recognizer import ExternalContentRecognizer
from .api import (
    ExternalContentRecognitionPort,
    ExternalMediaFetchPort,
    PerceptionArtifactCatalogPort,
    PerceptionDurableWorkPort,
    PerceptionWakeupPort,
    PerceptionWorkerPort,
)


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
        opportunity=opportunity,
        fetch=fetch,
        recognizer=recognizer,
        target_for=target_for,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )
    return PerceptionModule(worker)


__all__ = ("PerceptionModule", "bootstrap_perception")
