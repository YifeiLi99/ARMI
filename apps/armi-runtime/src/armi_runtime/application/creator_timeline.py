"""Runtime assembly of cross-owner Creator timeline details."""

from __future__ import annotations

from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_attention.api import (
    OpportunityAdmissionPort,
    OpportunityContextReadPort,
    OpportunityPurpose,
)
from armi_codex.api import CodexTaskSourceReadPort
from armi_cognition.api import CognitionOperationReadPort
from armi_evidence.api import EvidenceReadPort, EvidenceSourceKind
from armi_interaction.api import (
    InteractionCreatorTimelineProjection,
    InteractionCreatorTimelineProjectionPort,
)
from armi_kernel.application import ArtifactId
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction


class CreatorTimelineProjectionAssembler(InteractionCreatorTimelineProjectionPort):
    __slots__ = (
        "_catalog",
        "_codex",
        "_cognition",
        "_evidence",
        "_opportunity_admission",
        "_opportunity_read",
    )

    def __init__(
        self,
        *,
        evidence: EvidenceReadPort,
        opportunity_admission: OpportunityAdmissionPort,
        opportunity_read: OpportunityContextReadPort,
        cognition: CognitionOperationReadPort,
        catalog: ArtifactCatalogPort,
        codex: CodexTaskSourceReadPort,
    ) -> None:
        self._evidence = evidence
        self._opportunity_admission = opportunity_admission
        self._opportunity_read = opportunity_read
        self._cognition = cognition
        self._catalog = catalog
        self._codex = codex

    async def creator_input(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        interaction_id: UUID,
        purpose: str,
        content_digest: Digest,
        modality: str,
    ) -> InteractionCreatorTimelineProjection:
        transaction = unit_of_work.transaction
        if purpose == "codex_task_request":
            task_source = await self._codex.find_by_manifest_digest(
                transaction, manifest_digest=content_digest
            )
            evidence_id = (
                None
                if task_source is None
                else await self._evidence.find_by_codex_task_source(
                    transaction, task_source_id=task_source.task_source_id
                )
            )
        else:
            evidence_id = await self._evidence.find_by_interaction(
                transaction, interaction_id=interaction_id
            )
        if evidence_id is None:
            raise RuntimeError("CREATOR-TIMELINE-SOURCE")
        evidence = await self._evidence.snapshot(transaction, evidence_id=evidence_id)
        opportunity_purpose = (
            OpportunityPurpose.CONSIDER_CODEX_TASK
            if evidence.source_kind is EvidenceSourceKind.CODEX_TASK_SOURCE
            else OpportunityPurpose.CONSIDER_CREATOR_INPUT
        )
        opportunity_id = await self._opportunity_admission.find_external_evidence(
            transaction,
            evidence_id=evidence_id.value,
            purpose=opportunity_purpose,
        )
        if opportunity_id is None and modality != "live_voice":
            raise RuntimeError("CREATOR-TIMELINE-SOURCE")
        operation_ref = None
        if opportunity_id is not None:
            opportunity = await self._opportunity_read.context_snapshot(
                transaction, opportunity_id=opportunity_id.value
            )
            operation_ref = opportunity.root_opportunity_id
        artifact = await self._catalog.get(
            unit_of_work, ArtifactId(evidence.artifact_id)
        )
        return InteractionCreatorTimelineProjection(operation_ref, artifact, purpose)

    async def subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_commit_id: UUID,
        context_party_id: UUID,
    ) -> UUID:
        row = await (
            await transaction.execute(
                """SELECT cognitive_episode_id FROM armi.subject_commits
                   WHERE subject_commit_id = %s""",
                (subject_commit_id,),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("CREATOR-TIMELINE-SOURCE")
        opportunity_id = await self._cognition.opportunity_for_episode(
            transaction, episode_id=row[0]
        )
        if opportunity_id is None:
            raise RuntimeError("CREATOR-TIMELINE-SOURCE")
        snapshot = await self._opportunity_read.context_snapshot(
            transaction, opportunity_id=opportunity_id
        )
        if snapshot.context_party_id != context_party_id:
            raise RuntimeError("CREATOR-TIMELINE-SOURCE")
        return snapshot.root_opportunity_id


__all__ = ("CreatorTimelineProjectionAssembler",)
