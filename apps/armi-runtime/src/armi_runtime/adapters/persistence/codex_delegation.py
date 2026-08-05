"""Authoritative persistence for Codex task admission and verified settlement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CodexCleanupStatus,
    CodexDelegationViolation,
    CodexResultEvidenceKind,
    CodexTaskSourceDraft,
    CodexTaskSourceId,
    CodexVerificationStatus,
    CreatorInputAcceptance,
    CreatorInteractionId,
    EvidenceId,
    OpportunityId,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from .creator_input import CreatorInputContext
from .effect_grant_coordination import coordinate_dispatch_boundary
from .unit_of_work import PostgreSQLUnitOfWork

_BINDING = "armi.codex-runner.openai-python-sdk-v1"


@dataclass(frozen=True, slots=True)
class CodexDispatchSnapshot:
    outbox_id: UUID
    effect_id: UUID
    attempt_id: UUID
    attempt_no: int
    claim_owner: UUID
    claim_token: int
    operation_id: UUID
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
    __slots__ = ()

    async def admit_task_source(
        self,
        uow: PostgreSQLUnitOfWork,
        draft: CodexTaskSourceDraft,
    ) -> CodexTaskSourceId:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        subject = await (
            await connection.execute(
                """
                SELECT scene.scene_id, scene.primary_party_id
                FROM armi.subjects AS subject
                JOIN armi.interaction_scenes AS scene
                  ON scene.subject_id = subject.subject_id
                 AND scene.scene_key = 'default'
                 AND scene.current_status = 'open'
                WHERE subject.subject_id = %s AND subject.singleton_key = 1
                """,
                (draft.subject_id.value,),
            )
        ).fetchone()
        if subject is None:
            raise CodexDelegationViolation("CODEX-TASK-SUBJECT")
        await _require_artifact(
            connection,
            draft.source_bundle_artifact_id.value,
            draft.source_bundle_digest,
        )
        await _require_artifact(
            connection,
            draft.manifest_artifact_id.value,
            draft.manifest_digest,
        )
        scope_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "allowed_paths": list(draft.allowed_paths),
                    "forbidden_paths": list(draft.forbidden_paths),
                }
            )
        )
        await connection.execute(
            """
            INSERT INTO armi.codex_task_sources (
                codex_task_source_id, subject_id, source_bundle_artifact_id,
                source_bundle_digest, source_tree_digest, task_manifest_artifact_id,
                task_manifest_digest, path_scope_digest, validator_id,
                deadline_seconds, trace_id, schema_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            """,
            (
                draft.task_source_id.value,
                draft.subject_id.value,
                draft.source_bundle_artifact_id.value,
                draft.source_bundle_digest.value,
                draft.source_tree_digest.value,
                draft.manifest_artifact_id.value,
                draft.manifest_digest.value,
                scope_digest.value,
                draft.validator_id,
                draft.deadline_seconds,
                draft.trace_id.value,
            ),
        )
        evidence_id, opportunity_id = uuid7(), uuid7()
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, creator_interaction_id, subject_id, scene_id,
                creator_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status, codex_task_source_id,
                schema_version
            ) VALUES (%s,NULL,%s,%s,%s,%s,'codex_task_source','external_claim',
                'private','accepted',%s,1)
            """,
            (
                evidence_id,
                draft.subject_id.value,
                subject[0],
                subject[1],
                draft.manifest_artifact_id.value,
                draft.task_source_id.value,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, source_kind, source_ref,
                source_version, source_digest, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no, schema_version
            ) VALUES (%s,%s,%s,%s,%s,'consider_codex_task',
                'external_evidence',%s,1,%s,'eligible','open',%s,NULL,0,1)
            """,
            (
                opportunity_id,
                evidence_id,
                draft.subject_id.value,
                subject[0],
                subject[1],
                evidence_id,
                draft.manifest_digest.value,
                opportunity_id,
            ),
        )
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
                artifact_digest=draft.manifest_digest,
            )
        )
        return draft.task_source_id

    async def existing_creator_task(
        self,
        uow: PostgreSQLUnitOfWork,
        *,
        context: CreatorInputContext,
        idempotency_key: str,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT interaction.creator_interaction_id, evidence.evidence_id,
                       opportunity.opportunity_id, interaction.request_digest,
                       interaction.content_digest
                FROM armi.creator_input_interactions AS interaction
                JOIN armi.external_evidence AS evidence
                  ON evidence.creator_interaction_id=interaction.creator_interaction_id
                 AND evidence.source_kind='codex_task_source'
                JOIN armi.opportunities AS opportunity
                  ON opportunity.evidence_id=evidence.evidence_id
                 AND opportunity.purpose='consider_codex_task'
                WHERE interaction.creator_party_id=%s
                  AND interaction.scene_id=%s
                  AND interaction.purpose='codex_task_request'
                  AND interaction.idempotency_key=%s
                """,
                (
                    context.creator_party_id,
                    context.scene_id,
                    idempotency_key,
                ),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[3]) != request_digest.value:
            raise CodexDelegationViolation("CODEX-TASK-IDEMPOTENCY")
        return CreatorInputAcceptance(
            CreatorInteractionId(row[0]),
            EvidenceId(row[1]),
            OpportunityId(row[2]),
            Digest(str(row[3])),
            Digest(str(row[4])),
            False,
        )

    async def admit_creator_task_source(
        self,
        uow: PostgreSQLUnitOfWork,
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
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        if draft.subject_id.value != context.subject_id:
            raise CodexDelegationViolation("CODEX-TASK-SUBJECT")
        await _require_artifact(
            connection,
            draft.source_bundle_artifact_id.value,
            draft.source_bundle_digest,
        )
        await _require_artifact(
            connection,
            draft.manifest_artifact_id.value,
            draft.manifest_digest,
        )
        await _insert_task_source(connection, draft)
        interaction_id, evidence_id, opportunity_id, timeline_id = (
            uuid7(),
            uuid7(),
            uuid7(),
            uuid7(),
        )
        await connection.execute(
            """
            INSERT INTO armi.creator_input_interactions (
                creator_interaction_id, subject_id, scene_id, creator_party_id,
                purpose, idempotency_key, request_digest, content_digest,
                trace_id, schema_version
            ) VALUES (%s,%s,%s,%s,'codex_task_request',%s,%s,%s,%s,1)
            """,
            (
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                idempotency_key,
                request_digest.value,
                draft.manifest_digest.value,
                draft.trace_id.value,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, creator_interaction_id, subject_id, scene_id,
                creator_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status, codex_task_source_id,
                schema_version
            ) VALUES (%s,%s,%s,%s,%s,%s,'codex_task_source','external_claim',
                'private','accepted',%s,1)
            """,
            (
                evidence_id,
                interaction_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                draft.manifest_artifact_id.value,
                draft.task_source_id.value,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, source_kind, source_ref,
                source_version, source_digest, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no, schema_version
            ) VALUES (%s,%s,%s,%s,%s,'consider_codex_task',
                'external_evidence',%s,1,%s,'eligible','open',%s,NULL,0,1)
            """,
            (
                opportunity_id,
                evidence_id,
                context.subject_id,
                context.scene_id,
                context.creator_party_id,
                evidence_id,
                draft.manifest_digest.value,
                opportunity_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at, schema_version
            ) VALUES (%s,%s,'creator_input',%s,1,'accepted',statement_timestamp(),1)
            """,
            (timeline_id, context.scene_id, interaction_id),
        )
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
                request_digest=request_digest,
                artifact_digest=draft.manifest_digest,
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
        uow: PostgreSQLUnitOfWork,
        *,
        claim_owner: UUID,
    ) -> CodexDispatchSnapshot | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id, effect.effect_id,
                       operation.creator_response_operation_id,
                       operation.root_opportunity_id, effect.subject_id,
                       effect.interaction_scene_id, effect.creator_party_id,
                       source.codex_task_source_id,
                       source.source_bundle_artifact_id, source.source_bundle_digest,
                       source.source_tree_digest, source.task_manifest_artifact_id,
                       source.task_manifest_digest, source.validator_id,
                       source.deadline_seconds, effect.trace_id,
                       outbox.attempt_count, outbox.claim_token,
                       bundle.byte_size, bundle.media_type, bundle.logical_kind,
                       bundle.privacy_scope, bundle.integrity_status,
                       manifest.byte_size, manifest.media_type, manifest.logical_kind,
                       manifest.privacy_scope, manifest.integrity_status
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id = outbox.effect_id
                JOIN armi.creator_response_operations AS operation
                  ON operation.effect_id = effect.effect_id
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id = effect.action_intent_revision_id
                JOIN armi.codex_task_sources AS source
                  ON source.codex_task_source_id = revision.codex_task_source_id
                JOIN armi.artifacts AS bundle
                  ON bundle.artifact_id = source.source_bundle_artifact_id
                JOIN armi.artifacts AS manifest
                  ON manifest.artifact_id = source.task_manifest_artifact_id
                WHERE outbox.status = 'ready'
                  AND outbox.available_at <= statement_timestamp()
                  AND statement_timestamp() < outbox.dispatch_deadline
                  AND outbox.attempt_count = 0 AND outbox.max_attempts = 1
                  AND effect.status = 'registered'
                  AND effect.effect_kind = 'codex_delegation'
                ORDER BY outbox.available_at, outbox.effect_outbox_item_id
                FOR UPDATE OF outbox, effect SKIP LOCKED
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        attempt_id = uuid7()
        claim_token = int(row[17]) + 1
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "effect_id": str(row[1]),
                    "task_manifest_digest": str(row[12]),
                    "source_tree_digest": str(row[10]),
                }
            )
        )
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items
            SET status='claimed', claim_owner=%s,
                claim_expires_at=statement_timestamp()+interval '60 seconds',
                claim_token=%s, attempt_count=1
            WHERE effect_outbox_item_id=%s AND status='ready'
            """,
            (claim_owner, claim_token, row[0]),
        )
        await connection.execute(
            """
            INSERT INTO armi.effect_attempts (
                effect_attempt_id, effect_id, attempt_no, adapter_binding,
                request_digest, claim_token, dispatch_state, schema_version
            ) VALUES (%s,%s,1,%s,%s,%s,'prepared',1)
            """,
            (attempt_id, row[1], _BINDING, request_digest.value, claim_token),
        )
        await connection.execute(
            """
            UPDATE armi.effects SET status='dispatching', verification_status='pending',
                current_attempt_id=%s WHERE effect_id=%s AND status='registered'
            """,
            (attempt_id, row[1]),
        )
        await connection.execute(
            """
            UPDATE armi.creator_response_operations SET current_status='codex_dispatching'
            WHERE creator_response_operation_id=%s AND current_status='effect_registered'
            """,
            (row[2],),
        )
        return CodexDispatchSnapshot(
            row[0],
            row[1],
            attempt_id,
            1,
            claim_owner,
            claim_token,
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            _artifact(row[8], row[9], row[18:23]),
            Digest(str(row[10])),
            _artifact(row[11], row[12], row[23:28]),
            Digest(str(row[12])),
            str(row[13]),
            int(row[14]),
            TraceId(str(row[15])),
        )

    async def mark_dispatching(
        self, uow: PostgreSQLUnitOfWork, snapshot: CodexDispatchSnapshot
    ) -> bool:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        boundary = await coordinate_dispatch_boundary(
            uow,
            effect_id=snapshot.effect_id,
            attempt_id=snapshot.attempt_id,
            outbox_id=snapshot.outbox_id,
            claim_owner=snapshot.claim_owner,
            claim_token=snapshot.claim_token,
            expected_operation_status="codex_dispatching",
            cancelled_operation_status="codex_cancelled",
        )
        if boundary is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
        if not boundary.allowed:
            return False
        updated = await (
            await connection.execute(
                """
                UPDATE armi.effect_attempts
                SET dispatch_state='dispatching', dispatched_at=statement_timestamp()
                WHERE effect_attempt_id=%s AND dispatch_state='prepared'
                RETURNING effect_attempt_id
                """,
                (snapshot.attempt_id,),
            )
        ).fetchone()
        if updated is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
        return True

    async def heartbeat(
        self, uow: PostgreSQLUnitOfWork, snapshot: CodexDispatchSnapshot
    ) -> bool:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                UPDATE armi.effect_outbox_items
                SET claim_expires_at=statement_timestamp()+interval '60 seconds'
                WHERE effect_outbox_item_id=%s AND status='claimed'
                  AND claim_owner=%s AND claim_token=%s
                RETURNING effect_outbox_item_id
                """,
                (snapshot.outbox_id, snapshot.claim_owner, snapshot.claim_token),
            )
        ).fetchone()
        return row is not None

    async def settle(
        self,
        uow: PostgreSQLUnitOfWork,
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
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        current = await (
            await connection.execute(
                """
                SELECT outbox.effect_outbox_item_id
                FROM armi.effect_outbox_items AS outbox
                JOIN armi.effects AS effect ON effect.effect_id=outbox.effect_id
                JOIN armi.effect_attempts AS attempt
                  ON attempt.effect_attempt_id=effect.current_attempt_id
                WHERE outbox.effect_outbox_item_id=%s
                  AND outbox.status='claimed'
                  AND outbox.claim_owner=%s AND outbox.claim_token=%s
                  AND outbox.claim_expires_at > statement_timestamp()
                  AND effect.effect_id=%s AND effect.status='dispatching'
                  AND effect.verification_status='pending'
                  AND effect.current_attempt_id=%s
                  AND attempt.dispatch_state='dispatching'
                FOR UPDATE OF outbox, effect, attempt
                """,
                (
                    snapshot.outbox_id,
                    snapshot.claim_owner,
                    snapshot.claim_token,
                    snapshot.effect_id,
                    snapshot.attempt_id,
                ),
            )
        ).fetchone()
        if current is None:
            raise CodexDelegationViolation("CODEX-DELEGATION-STALE")
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
                validation_report_artifact_id, validation_digest,
                changed_path_count, execution_error_code, cleanup_error_code,
                schema_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
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
                validation.value,
                changed_path_count,
                execution_error_code,
                cleanup_error_code,
            ),
        )
        observation_id = uuid7()
        observation_kind = {
            CodexVerificationStatus.VERIFIED: "runner_verified",
            CodexVerificationStatus.FAILED: "runner_failed",
            CodexVerificationStatus.UNKNOWN: "runner_unknown",
            CodexVerificationStatus.CANCELLED: "runner_cancelled",
        }[status]
        reliability = (
            "inconclusive" if status is CodexVerificationStatus.UNKNOWN else "reliable"
        )
        observation_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "verification_id": str(verification_id),
                    "status": status.value,
                    "validation_digest": validation.value,
                }
            )
        )
        await connection.execute(
            """
            INSERT INTO armi.effect_observations (
                effect_observation_id, effect_id, effect_attempt_id,
                observation_kind, reliability, receiver_ref,
                observation_digest, schema_version
            ) VALUES (%s,%s,%s,%s,%s,NULL,%s,1)
            """,
            (
                observation_id,
                snapshot.effect_id,
                snapshot.attempt_id,
                observation_kind,
                reliability,
                observation_digest.value,
            ),
        )
        result_status = {
            CodexVerificationStatus.VERIFIED: "succeeded",
            CodexVerificationStatus.FAILED: "failed",
            CodexVerificationStatus.UNKNOWN: "unknown",
            CodexVerificationStatus.CANCELLED: "cancelled",
        }[status]
        terminal_error_code = (
            execution_error_code
            or cleanup_error_code
            or (
                "CODEX-DELEGATION-FAILED"
                if status is CodexVerificationStatus.FAILED
                else "CODEX-DELEGATION-UNKNOWN"
            )
        )
        effect_status = {
            CodexVerificationStatus.VERIFIED: "completed",
            CodexVerificationStatus.FAILED: "failed",
            CodexVerificationStatus.UNKNOWN: "unknown",
            CodexVerificationStatus.CANCELLED: "cancelled",
        }[status]
        verification_status = (
            "inconclusive" if status is CodexVerificationStatus.UNKNOWN else "verified"
        )
        settlement = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "effect_id": str(snapshot.effect_id),
                    "verification_id": str(verification_id),
                    "status": status.value,
                    "observation_digest": observation_digest.value,
                }
            )
        )
        await connection.execute(
            """
            UPDATE armi.effect_attempts
            SET dispatch_state='settled', result_status=%s, error_code=%s,
                settled_at=statement_timestamp()
            WHERE effect_attempt_id=%s AND dispatch_state='dispatching'
            """,
            (
                result_status,
                terminal_error_code
                if status
                in {CodexVerificationStatus.FAILED, CodexVerificationStatus.UNKNOWN}
                else None,
                snapshot.attempt_id,
            ),
        )
        await connection.execute(
            """
            UPDATE armi.effects
            SET status=%s, verification_status=%s,
                current_observation_id=%s, settlement_digest=%s,
                settled_at=statement_timestamp()
            WHERE effect_id=%s AND current_attempt_id=%s
            """,
            (
                effect_status,
                verification_status,
                observation_id,
                settlement.value,
                snapshot.effect_id,
                snapshot.attempt_id,
            ),
        )
        outbox_status = {
            CodexVerificationStatus.VERIFIED: "delivered",
            CodexVerificationStatus.FAILED: "dead",
            CodexVerificationStatus.UNKNOWN: "unknown",
            CodexVerificationStatus.CANCELLED: "cancelled",
        }[status]
        await connection.execute(
            """
            UPDATE armi.effect_outbox_items
            SET status=%s, claim_owner=NULL, claim_expires_at=NULL,
                delivered_at=CASE WHEN %s='delivered' THEN statement_timestamp() ELSE NULL END,
                cancelled_at=CASE WHEN %s='cancelled' THEN statement_timestamp() ELSE NULL END,
                last_error_code=%s
            WHERE effect_outbox_item_id=%s AND claim_owner=%s AND claim_token=%s
            """,
            (
                outbox_status,
                outbox_status,
                outbox_status,
                terminal_error_code if outbox_status in {"dead", "unknown"} else None,
                snapshot.outbox_id,
                snapshot.claim_owner,
                snapshot.claim_token,
            ),
        )
        operation_status = {
            CodexVerificationStatus.VERIFIED: "codex_result_pending",
            CodexVerificationStatus.FAILED: "codex_failed",
            CodexVerificationStatus.UNKNOWN: "codex_unknown",
            CodexVerificationStatus.CANCELLED: "codex_cancelled",
        }[status]
        await connection.execute(
            """
            UPDATE armi.creator_response_operations
            SET current_status=%s, reason_code=%s, completed_at=statement_timestamp()
            WHERE creator_response_operation_id=%s
            """,
            (
                operation_status,
                terminal_error_code
                if status
                in {CodexVerificationStatus.FAILED, CodexVerificationStatus.UNKNOWN}
                else cleanup_error_code,
                snapshot.operation_id,
            ),
        )
        evidence_id, opportunity_id, result_source_id = uuid7(), uuid7(), uuid7()
        evidence_ref = (
            artifacts["final_result"]
            if status is CodexVerificationStatus.VERIFIED
            else artifacts["result_evidence"]
        )
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, creator_interaction_id, subject_id, scene_id,
                creator_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status, codex_verification_id,
                schema_version
            ) VALUES (%s,NULL,%s,%s,%s,%s,'codex_result','external_claim',
                'private','accepted',%s,1)
            """,
            (
                evidence_id,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.creator_party_id,
                evidence_ref.artifact_id.value,
                verification_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                creator_party_id, purpose, source_kind, source_ref,
                source_version, source_digest, eligibility_status,
                current_disposition, root_opportunity_id,
                predecessor_opportunity_id, reconsideration_no, schema_version
            ) VALUES (%s,%s,%s,%s,%s,'consider_codex_result',
                'external_evidence',%s,1,%s,'eligible','open',%s,NULL,0,1)
            """,
            (
                opportunity_id,
                evidence_id,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.creator_party_id,
                evidence_id,
                evidence_ref.content_digest.value,
                opportunity_id,
            ),
        )
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
                evidence_artifact_id, evidence_digest, schema_version
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,1)
            """,
            (
                result_source_id,
                verification_id,
                evidence_id,
                opportunity_id,
                result_kind.value,
                evidence_ref.artifact_id.value,
                evidence_ref.content_digest.value,
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
                response_digest=settlement,
            )
        )
        return verification_id


async def _require_artifact(connection: Any, artifact_id: UUID, digest: Digest) -> None:
    row = await (
        await connection.execute(
            """
            SELECT content_digest, integrity_status, retention_status
            FROM armi.artifacts WHERE artifact_id=%s
            """,
            (artifact_id,),
        )
    ).fetchone()
    if (
        row is None
        or str(row[0]) != digest.value
        or str(row[1]) != "verified"
        or str(row[2]) != "retained"
    ):
        raise CodexDelegationViolation("CODEX-TASK-ARTIFACT")


async def _insert_task_source(connection: Any, draft: CodexTaskSourceDraft) -> None:
    scope_digest = Digest.from_bytes(
        rfc8785.dumps(
            {
                "allowed_paths": list(draft.allowed_paths),
                "forbidden_paths": list(draft.forbidden_paths),
            }
        )
    )
    await connection.execute(
        """
        INSERT INTO armi.codex_task_sources (
            codex_task_source_id, subject_id, source_bundle_artifact_id,
            source_bundle_digest, source_tree_digest, task_manifest_artifact_id,
            task_manifest_digest, path_scope_digest, validator_id,
            deadline_seconds, trace_id, schema_version
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
        """,
        (
            draft.task_source_id.value,
            draft.subject_id.value,
            draft.source_bundle_artifact_id.value,
            draft.source_bundle_digest.value,
            draft.source_tree_digest.value,
            draft.manifest_artifact_id.value,
            draft.manifest_digest.value,
            scope_digest.value,
            draft.validator_id,
            draft.deadline_seconds,
            draft.trace_id.value,
        ),
    )


def _artifact(artifact_id: UUID, digest: object, tail: tuple[Any, ...]) -> ArtifactRef:
    return ArtifactRef(
        ArtifactId(artifact_id),
        Digest(str(digest)),
        int(tail[0]),
        str(tail[1]),
        str(tail[2]),
        ArtifactPrivacyScope(str(tail[3])),
        ArtifactIntegrityStatus(str(tail[4])),
        1,
    )


__all__ = ("CodexDispatchSnapshot", "PostgreSQLCodexDelegationRepository")
