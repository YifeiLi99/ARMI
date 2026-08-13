"""Authoritative persistence for Codex task admission and verified settlement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort
from armi_effect.api import EffectCodexClaim, EffectCodexLifecyclePort
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceReadPort,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputContext,
    CreatorInputTransactionPort,
    CreatorInteractionId,
    InteractionIdentityPort,
    OpportunityId,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId
from armi_opportunity.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._delegation_contract import (
    CodexCleanupStatus,
    CodexDelegationViolation,
    CodexResultEvidenceKind,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
)
from .api import CodexTaskSourceReadPort

_BINDING = "armi.codex-runner.openai-python-sdk-v1"


@dataclass(frozen=True, slots=True)
class CodexDispatchSnapshot:
    outbox_id: UUID
    effect_id: UUID
    attempt_id: UUID
    attempt_no: int
    claim_owner: UUID
    claim_token: int
    operation_ref: UUID
    root_operation_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    task_source_id: UUID
    source_bundle: ArtifactRef
    source_tree_digest: Digest
    task_manifest: ArtifactRef
    task_manifest_digest: Digest
    validator_id: str
    deadline_seconds: int
    trace_id: TraceId


class PostgreSQLCodexDelegationRepository:
    __slots__ = (
        "_artifacts",
        "_effect",
        "_evidence",
        "_evidence_read",
        "_expression",
        "_identity",
        "_input",
        "_opportunity",
        "_sources",
    )

    def __init__(
        self,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
        effect: EffectCodexLifecyclePort,
        expression: ExpressionIntentReadPort,
        artifacts: ArtifactCatalogPort,
        sources: CodexTaskSourceReadPort,
        evidence_read: EvidenceReadPort,
        identity: InteractionIdentityPort,
        input_port: CreatorInputTransactionPort,
    ) -> None:
        self._evidence = evidence
        self._opportunity = opportunity
        self._effect = effect
        self._expression = expression
        self._artifacts = artifacts
        self._sources = sources
        self._evidence_read = evidence_read
        self._identity = identity
        self._input = input_port

    async def admit_task_source(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        draft: CodexTaskSourceDraft,
    ) -> CodexTaskSourceId:
        connection = uow.transaction
        existing = await (
            await connection.execute(
                """
                SELECT task_manifest_digest, source_bundle_digest,
                       source_tree_digest, validator_id
                FROM armi.codex_task_sources
                WHERE codex_task_source_id = %s
                """,
                (draft.task_source_id.value,),
            )
        ).fetchone()
        if existing is not None:
            if tuple(map(str, existing)) != (
                draft.manifest_digest.value,
                draft.source_bundle_digest.value,
                draft.source_tree_digest.value,
                draft.validator_id,
            ):
                raise CodexDelegationViolation("CODEX-TASK-IDEMPOTENCY")
            return draft.task_source_id
        subject = await self._identity.creator_context(
            connection,
            subject_id=draft.subject_id.value,
        )
        if subject is None:
            raise CodexDelegationViolation("CODEX-TASK-SUBJECT")
        await self._require_artifact(
            uow, draft.source_bundle_artifact_id.value, draft.source_bundle_digest
        )
        await self._require_artifact(
            uow, draft.manifest_artifact_id.value, draft.manifest_digest
        )
        await connection.execute(
            """
            INSERT INTO armi.codex_task_sources (
                codex_task_source_id, subject_id, source_bundle_artifact_id,
                source_bundle_digest, source_tree_digest, task_manifest_artifact_id,
                task_manifest_digest, validator_id,
                deadline_seconds, trace_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                draft.task_source_id.value,
                draft.subject_id.value,
                draft.source_bundle_artifact_id.value,
                draft.source_bundle_digest.value,
                draft.source_tree_digest.value,
                draft.manifest_artifact_id.value,
                draft.manifest_digest.value,
                draft.validator_id,
                draft.deadline_seconds,
                draft.trace_id.value,
            ),
        )
        evidence_id = uuid7()
        await self._evidence.accept(
            uow,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=draft.subject_id.value,
                scene_id=subject.scene_id,
                context_party_id=subject.party_id,
                artifact_id=draft.manifest_artifact_id.value,
                source_kind=EvidenceSourceKind.CODEX_TASK_SOURCE,
                privacy_scope=EvidencePrivacyScope.PRIVATE,
                codex_task_source_id=draft.task_source_id.value,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=draft.subject_id.value,
                scene_id=subject.scene_id,
                context_party_id=subject.party_id,
                purpose=OpportunityPurpose.CONSIDER_CODEX_TASK,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("delegate_codex_work"),
                "codex.task_source.admitted",
                AuditReference("codex_task_source", draft.task_source_id.value),
                AuditResultStatus.ACCEPTED,
                draft.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=draft.subject_id,
            )
        )
        return draft.task_source_id

    async def existing_creator_task(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        connection = uow.transaction
        interaction = await self._input.find_codex_task_input(
            connection,
            creator_party_id=context.creator_party_id,
            scene_id=context.scene_id,
            idempotency_key=idempotency_key,
        )
        if interaction is None:
            return None
        interaction_id, stored_request, content_digest = interaction
        if stored_request != request_digest:
            raise CodexDelegationViolation("CODEX-TASK-IDEMPOTENCY")
        source = await (
            await connection.execute(
                """
                SELECT codex_task_source_id FROM armi.codex_task_sources
                WHERE subject_id=%s AND task_manifest_digest=%s
                """,
                (context.subject_id, content_digest.value),
            )
        ).fetchone()
        if source is None:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        evidence_id = await self._evidence_read.find_by_codex_task_source(
            connection,
            task_source_id=source[0],
        )
        if evidence_id is None:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        opportunity = await self._opportunity.find_external_evidence(
            connection,
            evidence_id=evidence_id.value,
            purpose=OpportunityPurpose.CONSIDER_CODEX_TASK,
        )
        if opportunity is None:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        return CreatorInputAcceptance(
            CreatorInteractionId(interaction_id),
            evidence_id,
            OpportunityId(opportunity.value),
            stored_request,
            content_digest,
            False,
        )

    async def admit_creator_task_source(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
        draft: CodexTaskSourceDraft,
    ) -> CreatorInputAcceptance:
        existing = await self.existing_creator_task(
            uow,
            context=context,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if existing is not None:
            return existing
        connection = uow.transaction
        if draft.subject_id.value != context.subject_id:
            raise CodexDelegationViolation("CODEX-TASK-SUBJECT")
        await self._require_artifact(
            uow, draft.source_bundle_artifact_id.value, draft.source_bundle_digest
        )
        await self._require_artifact(
            uow, draft.manifest_artifact_id.value, draft.manifest_digest
        )
        await _insert_task_source(connection, draft)
        interaction_id, evidence_id = uuid7(), uuid7()
        await self._input.record_codex_task_input(
            connection,
            interaction_id=interaction_id,
            subject_id=context.subject_id,
            scene_id=context.scene_id,
            creator_party_id=context.creator_party_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            content_digest=draft.manifest_digest,
            trace_id=draft.trace_id,
        )
        await self._evidence.accept(
            uow,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.creator_party_id,
                artifact_id=draft.manifest_artifact_id.value,
                source_kind=EvidenceSourceKind.CODEX_TASK_SOURCE,
                privacy_scope=EvidencePrivacyScope.PRIVATE,
                codex_task_source_id=draft.task_source_id.value,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=context.subject_id,
                scene_id=context.scene_id,
                context_party_id=context.creator_party_id,
                purpose=OpportunityPurpose.CONSIDER_CODEX_TASK,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        opportunity_id = admitted.opportunity_id
        if opportunity_id is None:
            raise CodexDelegationViolation("CODEX-TASK-ADMISSION")
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("creator", context.creator_party_id),
                Purpose("delegate_codex_work"),
                "codex.task_source.admitted",
                AuditReference("codex_task_source", draft.task_source_id.value),
                AuditResultStatus.ACCEPTED,
                draft.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=draft.subject_id,
                request=AuditReference("creator_input", interaction_id),
            )
        )
        return CreatorInputAcceptance(
            CreatorInteractionId(interaction_id),
            EvidenceId(evidence_id),
            OpportunityId(opportunity_id),
            request_digest,
            draft.manifest_digest,
            True,
        )

    async def claim(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        *,
        claim_owner: UUID,
    ) -> CodexDispatchSnapshot | None:
        claim = await self._effect.claim_codex(uow, claim_owner=claim_owner)
        if claim is None:
            return None
        intent = await self._expression.intent_snapshot(
            uow.transaction,
            action_intent_id=claim.action_intent_id,
        )
        if intent.codex_task_source_id is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
        source = await self._sources.task_source(
            uow.transaction,
            task_source_id=intent.codex_task_source_id,
        )
        bundle = await self._artifacts.retained_ref_in(
            uow.transaction,
            ArtifactId(source.source_bundle_artifact_id),
        )
        manifest = await self._artifacts.retained_ref_in(
            uow.transaction,
            ArtifactId(source.task_manifest_artifact_id),
        )
        if bundle is None or manifest is None:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")
        return CodexDispatchSnapshot(
            claim.outbox_id,
            claim.effect_id,
            claim.attempt_id,
            1,
            claim.claim_owner,
            claim.claim_token,
            intent.operation_ref,
            intent.root_opportunity_id,
            claim.subject_id,
            claim.scene_id,
            claim.context_party_id,
            source.task_source_id,
            bundle,
            source.source_tree_digest,
            manifest,
            source.task_manifest_digest,
            source.validator_id,
            source.deadline_seconds,
            claim.trace_id,
        )

    async def mark_dispatching(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: CodexDispatchSnapshot
    ) -> bool:
        return await self._effect.mark_codex_dispatching(uow, _effect_claim(snapshot))

    async def heartbeat(
        self, uow: PostgreSQLRuntimeUnitOfWork, snapshot: CodexDispatchSnapshot
    ) -> bool:
        return await self._effect.heartbeat_codex(
            uow.transaction,
            _effect_claim(snapshot),
        )

    async def settle(
        self,
        uow: PostgreSQLRuntimeUnitOfWork,
        *,
        snapshot: CodexDispatchSnapshot,
        status: CodexVerificationStatus,
        cleanup_status: CodexCleanupStatus,
        artifacts: Mapping[str, ArtifactRef],
        source_tree_digest: Digest,
        final_tree_digest: Digest | None,
        patch_digest: Digest | None,
        changed_path_count: int,
        execution_error_code: str | None,
        cleanup_error_code: str | None,
    ) -> UUID:
        connection = uow.transaction
        verification_id = uuid7()
        validation = artifacts["validation_report"].content_digest
        event_transcript = artifacts.get("event_transcript")
        final_result = artifacts.get("final_result")
        patch = artifacts.get("patch")
        result_bundle = artifacts.get("result_bundle")
        diagnostics = artifacts.get("diagnostics")
        await connection.execute(
            """
            INSERT INTO armi.codex_verification_results (
                codex_verification_id, effect_id, effect_attempt_id,
                execution_status, cleanup_status, source_tree_digest,
                final_tree_digest, patch_digest, event_transcript_artifact_id,
                final_result_artifact_id, patch_artifact_id,
                result_bundle_artifact_id, diagnostics_artifact_id,
                validation_report_artifact_id,
                changed_path_count, execution_error_code, cleanup_error_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                verification_id,
                snapshot.effect_id,
                snapshot.attempt_id,
                status.value,
                cleanup_status.value,
                source_tree_digest.value,
                final_tree_digest.value if final_tree_digest else None,
                patch_digest.value if patch_digest else None,
                event_transcript.artifact_id.value
                if event_transcript is not None
                else None,
                final_result.artifact_id.value if final_result is not None else None,
                patch.artifact_id.value if patch is not None else None,
                result_bundle.artifact_id.value if result_bundle is not None else None,
                diagnostics.artifact_id.value if diagnostics is not None else None,
                artifacts["validation_report"].artifact_id.value,
                changed_path_count,
                execution_error_code,
                cleanup_error_code,
            ),
        )
        terminal_error_code = (
            execution_error_code
            or cleanup_error_code
            or (
                "CODEX-DELEGATION-FAILED"
                if status is CodexVerificationStatus.FAILED
                else "CODEX-DELEGATION-UNKNOWN"
            )
        )
        await self._effect.settle_codex(
            connection,
            claim=_effect_claim(snapshot),
            status=status.value,
            observation_digest=validation,
            error_code=(
                terminal_error_code
                if status
                in {CodexVerificationStatus.FAILED, CodexVerificationStatus.UNKNOWN}
                else None
            ),
        )
        evidence_id, result_source_id = uuid7(), uuid7()
        evidence_ref = (
            artifacts["final_result"]
            if status is CodexVerificationStatus.VERIFIED
            else artifacts["result_evidence"]
        )
        await self._evidence.accept(
            uow,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=snapshot.subject_id,
                scene_id=snapshot.scene_id,
                context_party_id=snapshot.creator_party_id,
                artifact_id=evidence_ref.artifact_id.value,
                source_kind=EvidenceSourceKind.CODEX_RESULT,
                privacy_scope=EvidencePrivacyScope.PRIVATE,
                codex_verification_id=verification_id,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=snapshot.subject_id,
                scene_id=snapshot.scene_id,
                context_party_id=snapshot.creator_party_id,
                purpose=OpportunityPurpose.CONSIDER_CODEX_RESULT,
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise CodexDelegationViolation("CODEX-RESULT-ADMISSION")
        opportunity_id = admitted.opportunity_id
        if opportunity_id is None:
            raise CodexDelegationViolation("CODEX-RESULT-ADMISSION")
        result_kind = {
            CodexVerificationStatus.VERIFIED: CodexResultEvidenceKind.VERIFIED_COMPLETION,
            CodexVerificationStatus.FAILED: CodexResultEvidenceKind.EXECUTION_FAILURE,
            CodexVerificationStatus.UNKNOWN: CodexResultEvidenceKind.OUTCOME_UNKNOWN,
            CodexVerificationStatus.CANCELLED: CodexResultEvidenceKind.CANCELLED,
        }[status]
        await connection.execute(
            """
            INSERT INTO armi.codex_result_sources (
                codex_result_source_id, codex_verification_id,
                evidence_id, opportunity_id, result_kind,
                evidence_artifact_id) VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                result_source_id,
                verification_id,
                evidence_id,
                opportunity_id,
                result_kind.value,
                evidence_ref.artifact_id.value,
            ),
        )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("delegate_codex_work"),
                "codex.delegation.settled",
                AuditReference("effect", snapshot.effect_id),
                AuditResultStatus.APPLIED
                if status is CodexVerificationStatus.VERIFIED
                else AuditResultStatus.FAILED,
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
            )
        )
        return verification_id

    async def _require_artifact(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: UUID,
        digest: Digest,
    ) -> None:
        ref = await self._artifacts.retained_ref_in(
            unit_of_work.transaction,
            ArtifactId(artifact_id),
        )
        if ref is None or ref.content_digest != digest:
            raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")


def _effect_claim(snapshot: CodexDispatchSnapshot) -> EffectCodexClaim:
    return EffectCodexClaim(
        snapshot.outbox_id,
        snapshot.effect_id,
        snapshot.attempt_id,
        snapshot.claim_owner,
        snapshot.claim_token,
        snapshot.task_source_id,
        snapshot.task_source_id,
        snapshot.subject_id,
        snapshot.scene_id,
        snapshot.creator_party_id,
        snapshot.trace_id,
    )


async def _insert_task_source(connection: Any, draft: CodexTaskSourceDraft) -> None:
    await connection.execute(
        """
        INSERT INTO armi.codex_task_sources (
            codex_task_source_id, subject_id, source_bundle_artifact_id,
            source_bundle_digest, source_tree_digest, task_manifest_artifact_id,
            task_manifest_digest, validator_id,
            deadline_seconds, trace_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            draft.task_source_id.value,
            draft.subject_id.value,
            draft.source_bundle_artifact_id.value,
            draft.source_bundle_digest.value,
            draft.source_tree_digest.value,
            draft.manifest_artifact_id.value,
            draft.manifest_digest.value,
            draft.validator_id,
            draft.deadline_seconds,
            draft.trace_id.value,
        ),
    )


__all__ = ("CodexDispatchSnapshot", "PostgreSQLCodexDelegationRepository")
