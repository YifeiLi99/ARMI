"""Fenced PostgreSQL startup recovery for currently manifested responsibilities."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import psycopg
import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RecoveryDecision,
    RecoveryFinding,
    RecoveryRunId,
    RecoveryStatus,
    RecoverySummary,
    RecoveryViolation,
    RuntimeAuthorityViolation,
    RuntimeFence,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.role_policy import physical_role_name

from .audit_events import PostgreSQLAuditWriter
from .recovery_responsibilities import (
    repair_outbox,
    repair_terminal_cognitive_responsibilities,
    repair_work,
)

_SEARCH_PATH = "pg_catalog, armi"
_RECOVERY_METRIC_KINDS = (
    "requeued_work_count",
    "terminal_work_count",
    "requeued_outbox_count",
    "dead_outbox_count",
    "resumable_work_count",
    "resumable_outbox_count",
    "critical_artifact_count",
    "resumable_opportunity_count",
    "resumable_cognitive_episode_count",
    "resumable_model_attempt_count",
    "resumable_candidate_validation_count",
    "resumable_subject_commit_count",
    "resumable_capability_request_count",
    "resumable_response_operation_count",
    "resumable_effect_count",
    "resumable_effect_outbox_count",
    "resumable_effect_attempt_count",
    "reliable_effect_observation_count",
    "creator_response_delivery_count",
    "resumable_web_observation_count",
    "unknown_web_observation_attempt_count",
    "resumable_web_research_intent_count",
    "pending_web_evidence_acceptance_count",
    "resumable_web_cognition_count",
    "resumable_admin_correction_work_count",
    "resumable_codex_task_count",
    "resumable_codex_effect_count",
    "pending_codex_result_acceptance_count",
)


@dataclass(frozen=True, slots=True)
class _Scan:
    recovery_run_id: UUID
    findings: tuple[RecoveryFinding, ...]
    critical_artifacts: tuple[ArtifactRef, ...]
    requeued_work: int
    terminal_work: int
    requeued_outbox: int
    dead_outbox: int


async def _configure(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLRuntimeRecovery:
    """Classify and repair startup responsibility under one current fence."""

    __slots__ = (
        "_admission",
        "_environment_id",
        "_expected_role",
        "_pool",
        "_pool_timeout_seconds",
        "_storage",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        data_root: Path,
        max_object_bytes: int,
        pool_timeout_seconds: int,
        authority_admission: Callable[[], RuntimeFence],
    ) -> None:
        if environment_id.version != 7 or not data_root.is_absolute():
            raise ValueError("recovery environment declaration is invalid")
        if (
            type(pool_timeout_seconds) is not int
            or pool_timeout_seconds <= 0
            or not callable(authority_admission)
        ):
            raise ValueError("recovery pool declaration is invalid")
        self._environment_id = environment_id
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout_seconds = pool_timeout_seconds
        self._admission = authority_admission
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        )

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise RecoveryViolation("REC-ROLE-IDENTITY")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-runtime-recovery",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
            await self._storage.prepare()
        except psycopg.Error, PoolTimeout, ArtifactViolation:
            raise RecoveryViolation("REC-DEPENDENCY") from None

    async def close(self) -> None:
        await self._pool.close()

    async def recover(self) -> RecoverySummary:
        fence = self._require_fence()
        try:
            scan = await self._start_and_repair(fence)
            artifact_findings = await self._verify_artifacts(scan.critical_artifacts)
            return await self._finalize(
                fence,
                scan,
                (*scan.findings, *artifact_findings),
            )
        except RecoveryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise RecoveryViolation("REC-DATABASE") from None

    async def _start_and_repair(self, fence: RuntimeFence) -> _Scan:
        async with (
            self._pool.connection(
                timeout=float(self._pool_timeout_seconds)
            ) as connection,
            connection.transaction(),
        ):
            await self._verify_fence(connection, fence)
            writer = PostgreSQLAuditWriter(connection)
            await self._abandon_old_runs(connection, writer, fence)
            run_id, inserted = await self._running_row(connection, fence)
            if inserted:
                await writer.append(_audit(fence, "runtime.recovery.started", run_id))
            findings: list[RecoveryFinding] = []
            continuity, artifacts = await self._continuity(connection, fence)
            findings.extend(continuity)
            work = await repair_work(connection, writer, fence, _audit)
            findings.extend(work[0])
            outbox = await repair_outbox(connection, writer, fence, _audit)
            findings.extend(outbox[0])
            findings.extend(
                await repair_terminal_cognitive_responsibilities(
                    connection, writer, fence, _audit
                )
            )
            await self._verify_fence(connection, fence)
            return _Scan(
                recovery_run_id=run_id,
                findings=tuple(sorted(findings, key=_finding_key)),
                critical_artifacts=artifacts,
                requeued_work=work[1],
                terminal_work=work[2],
                requeued_outbox=outbox[1],
                dead_outbox=outbox[2],
            )

    async def _abandon_old_runs(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        writer: PostgreSQLAuditWriter,
        fence: RuntimeFence,
    ) -> None:
        rows = await (
            await connection.execute(
                """
                SELECT run.recovery_run_id
                FROM armi.runtime_recovery_runs AS run
                JOIN armi.runtime_instances AS instance
                  ON instance.runtime_instance_id = run.runtime_instance_id
                WHERE run.status = 'running'
                  AND run.runtime_instance_id <> %s
                  AND instance.status IN ('fenced', 'stopped')
                FOR UPDATE OF run
                """,
                (fence.runtime_instance_id.value,),
            )
        ).fetchall()
        for row in rows:
            digest = _summary_digest(
                {
                    "status": "abandoned",
                    "reason": "superseded_runtime_instance",
                }
            )
            await connection.execute(
                """
                UPDATE armi.runtime_recovery_runs
                SET status = 'abandoned',
                    completed_at = statement_timestamp(),
                    blocker_count = 1,
                    summary_digest = %s
                WHERE recovery_run_id = %s
                  AND status = 'running'
                """,
                (digest.value, row[0]),
            )
            await writer.append(_audit(fence, "runtime.recovery.abandoned", row[0]))

    async def _running_row(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        fence: RuntimeFence,
    ) -> tuple[UUID, bool]:
        existing = await (
            await connection.execute(
                """
                SELECT recovery_run_id, status
                FROM armi.runtime_recovery_runs
                WHERE runtime_instance_id = %s
                FOR UPDATE
                """,
                (fence.runtime_instance_id.value,),
            )
        ).fetchone()
        if existing is not None:
            if str(existing[1]) != "running":
                raise RecoveryViolation("REC-ALREADY-COMPLETED")
            await self._validate_metric_set(connection, existing[0])
            return existing[0], False
        run_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.runtime_recovery_runs (
                recovery_run_id,
                runtime_instance_id,
                subject_id,
                life_generation_id,
                bundle_activation_id,
                fence_token,
                status)
            VALUES (%s, %s, %s, %s, %s, %s, 'running')
            """,
            (
                run_id,
                fence.runtime_instance_id.value,
                fence.subject_id,
                fence.life_generation_id,
                fence.bundle_activation_id,
                fence.fence_token,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.runtime_recovery_metrics (
                recovery_run_id, metric_kind, metric_value
            )
            SELECT %s, metric_kind, 0
            FROM unnest(%s::text[]) AS metric_kind
            """,
            (run_id, list(_RECOVERY_METRIC_KINDS)),
        )
        await self._validate_metric_set(connection, run_id)
        return run_id, True

    async def _validate_metric_set(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        run_id: UUID,
    ) -> None:
        rows = await (
            await connection.execute(
                """SELECT metric_kind FROM armi.runtime_recovery_metrics
                   WHERE recovery_run_id = %s ORDER BY metric_kind""",
                (run_id,),
            )
        ).fetchall()
        if tuple(str(row[0]) for row in rows) != tuple(sorted(_RECOVERY_METRIC_KINDS)):
            raise RecoveryViolation("REC-METRIC-SET")

    async def _continuity(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        fence: RuntimeFence,
    ) -> tuple[tuple[RecoveryFinding, ...], tuple[ArtifactRef, ...]]:
        findings: list[RecoveryFinding] = []
        row = await (
            await connection.execute(
                """
                SELECT
                    subject.subject_id,
                    subject.current_generation_id,
                    subject.current_bundle_activation_id,
                    activation.manifest_artifact_id,
                    prompt_revision.content_artifact_id,
                    (
                        SELECT count(*)
                        FROM armi.subject_component_heads AS head
                        WHERE head.subject_id = subject.subject_id
                          AND head.component_kind IN ('self', 'mind', 'life_mode')
                    ),
                    (
                        SELECT count(*)
                        FROM armi.interaction_scenes AS scene
                        JOIN armi.parties AS creator
                          ON creator.party_id = scene.primary_party_id
                         AND creator.party_kind = 'creator'
                         AND creator.creator_role = 'unique_primary_creator'
                         AND creator.status = 'active'
                        WHERE scene.subject_id = subject.subject_id
                          AND scene.scene_key = 'default'
                          AND scene.scene_kind = 'creator_dialogue'
                          AND scene.audience_scope = 'creator'
                          AND scene.current_status = 'open'
                          AND scene.closed_at IS NULL
                    )
                FROM armi.subjects AS subject
                JOIN armi.runtime_bundle_activations AS activation
                  ON activation.bundle_activation_id
                    = subject.current_bundle_activation_id
                 AND activation.status = 'current'
                JOIN armi.prompt_documents AS prompt
                  ON prompt.subject_id = subject.subject_id
                 AND prompt.prompt_kind = 'personality_anchor'
                 AND prompt.write_authority = 'fixed'
                JOIN armi.prompt_revisions AS prompt_revision
                  ON prompt_revision.prompt_revision_id = prompt.current_revision_id
                WHERE subject.singleton_key = 1
                  AND subject.status = 'active'
                """
            )
        ).fetchone()
        if (
            row is None
            or row[0] != fence.subject_id
            or row[1] != fence.life_generation_id
            or row[2] != fence.bundle_activation_id
            or int(row[5]) != 3
            or int(row[6]) != 1
        ):
            findings.append(
                RecoveryFinding(
                    "subject_continuity",
                    RecoveryDecision.BLOCKED,
                    "REC-SUBJECT-INVALID",
                )
            )
            return tuple(findings), ()
        refs: list[ArtifactRef] = []
        for artifact_id in (row[3], row[4]):
            artifact_row = await (
                await connection.execute(
                    """
                    SELECT
                        artifact_id,
                        content_digest,
                        byte_size,
                        media_type,
                        logical_kind,
                        privacy_scope,
                        integrity_status
                    FROM armi.artifacts
                    WHERE artifact_id = %s
                    """,
                    (artifact_id,),
                )
            ).fetchone()
            if artifact_row is None:
                findings.append(
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.BLOCKED,
                        "REC-ARTIFACT-MISSING",
                        artifact_id,
                    )
                )
                continue
            try:
                refs.append(_artifact_ref(artifact_row))
            except ArtifactViolation:
                findings.append(
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.BLOCKED,
                        "REC-ARTIFACT-INVALID",
                        artifact_id,
                    )
                )
        return tuple(findings), tuple(refs)

    async def _verify_artifacts(
        self,
        refs: tuple[ArtifactRef, ...],
    ) -> tuple[RecoveryFinding, ...]:
        findings: list[RecoveryFinding] = []
        for ref in refs:
            if ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED:
                findings.append(
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.BLOCKED,
                        "REC-ARTIFACT-INVALID",
                        ref.artifact_id.value,
                    )
                )
                continue
            try:
                stream = await self._storage.open_verified(ref)
                await stream.close()
            except ArtifactViolation as error:
                reason = (
                    "REC-ARTIFACT-MISSING"
                    if error.code == "ART-MISSING"
                    else "REC-ARTIFACT-CORRUPT"
                )
                findings.append(
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.BLOCKED,
                        reason,
                        ref.artifact_id.value,
                    )
                )
            else:
                findings.append(
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.VERIFIED,
                        "REC-ARTIFACT-VERIFIED",
                        ref.artifact_id.value,
                    )
                )
        return tuple(findings)

    async def _finalize(
        self,
        fence: RuntimeFence,
        scan: _Scan,
        findings: tuple[RecoveryFinding, ...],
    ) -> RecoverySummary:
        sorted_findings = tuple(sorted(findings, key=_finding_key))
        blockers = sum(
            value.decision is RecoveryDecision.BLOCKED for value in sorted_findings
        )
        critical = sum(
            value.kind == "critical_artifact"
            and value.decision is RecoveryDecision.VERIFIED
            for value in sorted_findings
        )
        async with (
            self._pool.connection(
                timeout=float(self._pool_timeout_seconds)
            ) as connection,
            connection.transaction(),
        ):
            await self._verify_fence(connection, fence)
            await self._record_artifact_failures(connection, fence, sorted_findings)
            backfilled = await (
                await connection.execute(
                    """
                    WITH source AS (
                        SELECT
                            episode.cognitive_episode_id,
                            episode.subject_id,
                            episode.trace_id,
                            attempt.model_attempt_id,
                            artifact.content_digest
                        FROM armi.cognitive_episodes AS episode
                        JOIN armi.cognitive_attempts AS attempt
                          ON attempt.cognitive_episode_id
                           = episode.cognitive_episode_id
                         AND attempt.dispatch_status = 'settled'
                         AND attempt.result_status = 'succeeded'
                        JOIN armi.artifacts AS artifact
                          ON artifact.artifact_id = attempt.response_artifact_id
                        WHERE episode.status = 'model_returned'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM armi.durable_work AS existing
                              WHERE existing.owner_kind = 'cognitive_episode'
                                AND existing.owner_ref
                                  = episode.cognitive_episode_id
                                AND existing.work_kind
                                  = 'cognition.candidate.validate'
                          )
                    ),
                    inserted AS (
                        INSERT INTO armi.durable_work (
                            work_id, work_kind, owner_kind, owner_ref,
                            subject_id, idempotency_key, payload_kind,
                            payload_ref, payload_digest, priority, not_before,
                            deadline_at, status, max_attempts, attempt_count,
                            lease_token, trace_id
                        )
                        SELECT
                            uuidv7(), 'cognition.candidate.validate',
                            'cognitive_episode', cognitive_episode_id,
                            subject_id, 'candidate:' || cognitive_episode_id::text,
                            'model_attempt', model_attempt_id, content_digest,
                            50, statement_timestamp(),
                            statement_timestamp() + interval '3600 seconds',
                            'ready', 2, 0, 0, trace_id
                        FROM source
                        RETURNING
                            work_id, owner_ref, subject_id,
                            payload_digest, trace_id
                    )
                    SELECT
                        work_id, owner_ref, subject_id,
                        payload_digest, trace_id
                    FROM inserted
                    """
                )
            ).fetchall()
            for work_id, episode_id, subject_id, payload_digest, trace_id in backfilled:
                await connection.execute(
                    """
                    INSERT INTO armi.outbox_items (
                        outbox_item_id, work_id, message_kind,
                        payload_digest, status, available_at,
                        claim_token, attempt_count, max_attempts,
                        trace_id)
                    VALUES (
                        uuidv7(), %s, 'work.available', %s, 'ready',
                        statement_timestamp(), 0, 0, 2, %s)
                    """,
                    (work_id, payload_digest, trace_id),
                )
                await PostgreSQLAuditWriter(connection).append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference(
                            "runtime",
                            fence.runtime_instance_id.value,
                        ),
                        Purpose("cognition.candidate"),
                        "cognition.candidate.queued",
                        AuditReference("cognitive_episode", episode_id),
                        AuditResultStatus.WAITING,
                        TraceId(str(trace_id)),
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(subject_id),
                        request_digest=Digest(str(payload_digest)),
                    )
                )
            response_backfill = await (
                await connection.execute(
                    """
                    SELECT response.operation_id,
                           response.subject_id,
                           revision.action_intent_revision_id,
                           revision.response_digest,
                           interaction.trace_id
                    FROM armi.action_operations AS response
                    JOIN armi.action_intents AS intent
                      ON intent.action_intent_id = response.action_intent_id
                    JOIN armi.action_intent_revisions AS revision
                      ON revision.action_intent_revision_id =
                         intent.current_revision_id
                    JOIN armi.opportunities AS opportunity
                      ON opportunity.opportunity_id =
                         response.root_opportunity_id
                    JOIN armi.external_evidence AS evidence
                      ON evidence.evidence_id = opportunity.evidence_id
                    JOIN armi.party_input_interactions AS interaction
                      ON interaction.interaction_id =
                         evidence.interaction_id
                    WHERE response.phase = 'admitted'
                      AND response.outcome IS NULL
                      AND response.registration_work_id IS NULL
                    ORDER BY response.operation_id
                    FOR UPDATE OF response
                    """
                )
            ).fetchall()
            for (
                response_operation_id,
                subject_id,
                action_revision_id,
                response_digest,
                trace_id,
            ) in response_backfill:
                work_id = uuid7()
                await connection.execute(
                    """
                    INSERT INTO armi.durable_work (
                        work_id, work_kind, owner_kind, owner_ref,
                        subject_id, idempotency_key, payload_kind,
                        payload_ref, payload_digest, priority, not_before,
                        deadline_at, status, max_attempts, attempt_count,
                        lease_token, trace_id) VALUES (
                        %s, 'effect.register', 'creator_response_operation', %s,
                        %s, %s, 'action_intent_revision', %s, %s, 50,
                        statement_timestamp(),
                        statement_timestamp() + interval '3600 seconds',
                        'ready', 2, 0, 0, %s)
                    """,
                    (
                        work_id,
                        response_operation_id,
                        subject_id,
                        f"effect:{response_operation_id}",
                        action_revision_id,
                        response_digest,
                        trace_id,
                    ),
                )
                await connection.execute(
                    """
                    INSERT INTO armi.outbox_items (
                        outbox_item_id, work_id, message_kind,
                        payload_digest, status, available_at,
                        claim_token, attempt_count, max_attempts,
                        trace_id) VALUES (
                        uuidv7(), %s, 'work.available', %s, 'ready',
                        statement_timestamp(), 0, 0, 2, %s)
                    """,
                    (work_id, response_digest, trace_id),
                )
                updated = await (
                    await connection.execute(
                        """
                        UPDATE armi.action_operations
                        SET registration_work_id = %s
                        WHERE operation_id = %s
                          AND current_status = 'accepted'
                          AND registration_work_id IS NULL
                        RETURNING operation_id
                        """,
                        (work_id, response_operation_id),
                    )
                ).fetchone()
                if updated is None:
                    raise RecoveryViolation("REC-EFFECT-INVALID")
                await PostgreSQLAuditWriter(connection).append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference(
                            "runtime",
                            fence.runtime_instance_id.value,
                        ),
                        Purpose("effect.registration"),
                        "effect.registration.queued",
                        AuditReference(
                            "creator_response_operation",
                            response_operation_id,
                        ),
                        AuditResultStatus.WAITING,
                        TraceId(str(trace_id)),
                        AuditSensitivity.PRIVATE,
                        subject_id=SubjectId(subject_id),
                        request_digest=Digest(str(response_digest)),
                    )
                )
            await connection.execute(
                """
                UPDATE armi.cognitive_attempts AS attempt
                SET dispatch_status = 'settled',
                    result_status = 'cancelled',
                    error_code = 'MODEL-RECOVERY-PRE-DISPATCH',
                    settled_at = statement_timestamp()
                FROM armi.durable_work AS work
                WHERE attempt.work_id = work.work_id
                  AND attempt.dispatch_status = 'prepared'
                  AND work.status = 'ready'
                """
            )
            await connection.execute(
                """
                UPDATE armi.cognitive_attempts AS attempt
                SET dispatch_status = 'settled',
                    result_status = 'outcome_unknown',
                    error_code = 'MODEL-OUTCOME-UNKNOWN',
                    settled_at = statement_timestamp()
                FROM armi.durable_work AS work
                WHERE attempt.work_id = work.work_id
                  AND attempt.dispatch_status = 'dispatched'
                  AND work.status = 'ready'
                """
            )
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes AS episode
                SET status = 'prepared'
                FROM armi.durable_work AS work
                WHERE work.owner_kind = 'cognitive_episode'
                  AND work.owner_ref = episode.cognitive_episode_id
                  AND work.work_kind = 'cognition.model.invoke'
                  AND work.status = 'ready'
                  AND episode.status = 'calling_model'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM armi.cognitive_attempts AS attempt
                      WHERE attempt.cognitive_episode_id
                          = episode.cognitive_episode_id
                        AND attempt.dispatch_status <> 'settled'
                  )
                """
            )
            counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE status = 'ready'
                              AND deadline_at > statement_timestamp()
                              AND attempt_count < max_attempts
                        ),
                        (
                            SELECT count(*)
                            FROM armi.outbox_items
                            WHERE status = 'ready'
                              AND attempt_count < max_attempts
                        ),
                        (
                            SELECT count(*)
                            FROM armi.opportunities AS opportunity
                            JOIN armi.external_evidence AS evidence
                              ON evidence.evidence_id = opportunity.evidence_id
                             AND evidence.subject_id = opportunity.subject_id
                             AND evidence.scene_id = opportunity.scene_id
                             AND evidence.context_party_id
                               = opportunity.context_party_id
                            JOIN armi.party_input_interactions AS interaction
                              ON interaction.interaction_id
                               = evidence.interaction_id
                             AND interaction.subject_id = evidence.subject_id
                             AND interaction.scene_id = evidence.scene_id
                             AND interaction.source_party_id
                               = evidence.context_party_id
                            WHERE opportunity.current_disposition = 'open'
                              AND opportunity.eligibility_status = 'eligible'
                              AND opportunity.available_after
                                  <= statement_timestamp()
                              AND opportunity.expires_at IS NULL
                        ),
                        (
                            SELECT count(*)
                            FROM armi.cognitive_episodes AS episode
                            JOIN armi.opportunities AS opportunity
                              ON opportunity.opportunity_id
                               = episode.opportunity_id
                             AND opportunity.current_disposition = 'selected'
                            JOIN armi.durable_work AS work
                              ON work.owner_kind = 'cognitive_episode'
                             AND work.owner_ref = episode.cognitive_episode_id
                             AND work.work_kind = 'cognition.context.prepare'
                            WHERE (
                                episode.status = 'preparing'
                                AND work.status IN ('ready', 'leased')
                            )
                            OR (
                                episode.status = 'prepared'
                                AND work.status = 'completed'
                                AND work.result_kind = 'cognitive_episode'
                                AND work.result_ref = episode.cognitive_episode_id
                            )
                        ),
                        (
                            SELECT count(*)
                            FROM armi.cognitive_episodes AS episode
                            JOIN armi.durable_work AS work
                              ON work.owner_kind = 'cognitive_episode'
                             AND work.owner_ref = episode.cognitive_episode_id
                             AND work.work_kind = 'cognition.candidate.validate'
                            WHERE (
                                episode.status IN ('model_returned', 'validating')
                                AND work.status IN ('ready', 'leased')
                            )
                            OR (
                                episode.status IN (
                                    'candidate_validated',
                                    'candidate_rejected'
                                )
                                AND work.status = 'completed'
                                AND work.result_kind = 'candidate_validation'
                                AND EXISTS (
                                    SELECT 1
                                    FROM armi.cognitive_candidate_validations
                                        AS validation
                                    WHERE validation.candidate_validation_id
                                        = work.result_ref
                                      AND validation.cognitive_episode_id
                                        = episode.cognitive_episode_id
                                )
                            )
                        ),
                        (
                            SELECT count(*)
                            FROM armi.cognitive_episodes AS episode
                            JOIN armi.durable_work AS work
                              ON work.owner_kind = 'cognitive_episode'
                             AND work.owner_ref = episode.cognitive_episode_id
                             AND work.work_kind = 'cognition.model.invoke'
                            WHERE (
                                episode.status = 'prepared'
                                AND work.status IN ('ready', 'leased')
                            )
                            OR (
                                episode.status = 'calling_model'
                                AND work.status = 'leased'
                                AND EXISTS (
                                    SELECT 1
                                    FROM armi.cognitive_attempts AS attempt
                                    WHERE attempt.cognitive_episode_id
                                        = episode.cognitive_episode_id
                                      AND attempt.work_id = work.work_id
                                      AND attempt.dispatch_status
                                        IN ('prepared', 'dispatched')
                                )
                            )
                            OR (
                                episode.status = 'model_returned'
                                AND work.status = 'completed'
                                AND work.result_kind = 'model_attempt'
                                AND EXISTS (
                                    SELECT 1
                                    FROM armi.cognitive_attempts AS attempt
                                    WHERE attempt.model_attempt_id = work.result_ref
                                      AND attempt.cognitive_episode_id
                                        = episode.cognitive_episode_id
                                      AND attempt.dispatch_status = 'settled'
                                      AND attempt.result_status = 'succeeded'
                                )
                            )
                        ),
                        (
                            SELECT count(*)
                            FROM armi.cognitive_episodes AS episode
                            JOIN armi.durable_work AS work
                              ON work.owner_kind = 'cognitive_episode'
                             AND work.owner_ref = episode.cognitive_episode_id
                             AND work.work_kind = 'cognition.subject.commit'
                            WHERE (
                                episode.status IN (
                                    'candidate_validated',
                                    'committing'
                                )
                                AND work.status IN ('ready', 'leased')
                            )
                            OR (
                                episode.status IN ('completed', 'stale')
                                AND work.status = 'completed'
                                AND work.result_kind = 'candidate_application'
                                AND EXISTS (
                                    SELECT 1
                                    FROM armi.cognitive_candidate_applications
                                        AS application
                                    WHERE application.candidate_application_id
                                        = work.result_ref
                                      AND application.cognitive_episode_id
                                        = episode.cognitive_episode_id
                                )
                            )
                        ),
                        (
                            SELECT count(*)
                            FROM armi.opportunities AS opportunity
                            LEFT JOIN armi.external_evidence AS evidence
                              ON evidence.evidence_id = opportunity.evidence_id
                             AND evidence.subject_id = opportunity.subject_id
                             AND evidence.scene_id = opportunity.scene_id
                             AND evidence.context_party_id
                               = opportunity.context_party_id
                            LEFT JOIN armi.party_input_interactions AS interaction
                              ON interaction.interaction_id
                               = evidence.interaction_id
                             AND interaction.subject_id = evidence.subject_id
                             AND interaction.scene_id = evidence.scene_id
                             AND interaction.source_party_id
                               = evidence.context_party_id
                            WHERE opportunity.purpose = 'consider_creator_input'
                              AND (
                                  evidence.evidence_id IS NULL
                               OR interaction.interaction_id IS NULL
                               OR opportunity.current_disposition
                                  NOT IN (
                                      'open',
                                      'selected',
                                      'resolved',
                                      'superseded'
                                  )
                               OR opportunity.eligibility_status <> 'eligible'
                               OR opportunity.expires_at IS NOT NULL
                               OR evidence.source_kind <> 'creator_input'
                               OR evidence.trust_status <> 'external_claim'
                               OR evidence.privacy_scope <> 'creator_visible'
                               OR evidence.acceptance_status <> 'accepted'
                               OR interaction.purpose <> 'creator_message'
                               OR (
                                   opportunity.current_disposition = 'open'
                                   AND EXISTS (
                                       SELECT 1
                                       FROM armi.cognitive_episodes AS episode
                                       WHERE episode.opportunity_id
                                         = opportunity.opportunity_id
                                   )
                               )
                               OR (
                                   opportunity.current_disposition = 'selected'
                                   AND NOT EXISTS (
                                       SELECT 1
                                       FROM armi.cognitive_episodes AS episode
                                       WHERE episode.opportunity_id
                                         = opportunity.opportunity_id
                                         AND (
                                             (
                                                 episode.status = 'preparing'
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.context.prepare'
                                                       AND work.status
                                                         IN ('ready', 'leased')
                                                 )
                                             )
                                             OR (
                                                 episode.status
                                                   IN ('prepared', 'calling_model')
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.context.prepare'
                                                       AND work.status = 'completed'
                                                 )
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.model.invoke'
                                                       AND work.status
                                                         IN ('ready', 'leased')
                                                 )
                                             )
                                             OR (
                                                 episode.status = 'model_returned'
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.model.invoke'
                                                       AND work.status = 'completed'
                                                       AND work.result_kind
                                                         = 'model_attempt'
                                                 )
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.candidate.validate'
                                                       AND work.status
                                                         IN ('ready', 'leased')
                                                 )
                                             )
                                             OR (
                                                 episode.status = 'validating'
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.candidate.validate'
                                                       AND work.status
                                                         IN ('ready', 'leased')
                                                 )
                                             )
                                             OR (
                                                 episode.status IN (
                                                     'candidate_validated',
                                                     'candidate_rejected'
                                                 )
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     JOIN armi.cognitive_candidate_validations
                                                         AS validation
                                                       ON validation.candidate_validation_id
                                                         = work.result_ref
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.work_kind
                                                         = 'cognition.candidate.validate'
                                                       AND work.status = 'completed'
                                                       AND work.result_kind
                                                         = 'candidate_validation'
                                                       AND validation.cognitive_episode_id
                                                         = episode.cognitive_episode_id
                                                 )
                                             )
                                             OR (
                                                 episode.status = 'failed'
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.status = 'failed'
                                                 )
                                             )
                                             OR (
                                                 episode.status = 'cancelled'
                                                 AND EXISTS (
                                                     SELECT 1
                                                     FROM armi.durable_work AS work
                                                     WHERE work.owner_kind
                                                         = 'cognitive_episode'
                                                       AND work.owner_ref
                                                         = episode.cognitive_episode_id
                                                       AND work.status = 'cancelled'
                                                 )
                                             )
                                         )
                                   )
                               )
                              )
                        )
                    FROM armi.durable_work
                    """
                )
            ).fetchone()
            assert counts is not None
            capability_counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE request.current_status IN (
                                'pending', 'granted', 'limited'
                            )
                        ),
                        count(*) FILTER (
                            WHERE capability.capability_id IS NULL
                               OR commit.subject_commit_id IS NULL
                               OR scene.scene_id IS NULL
                               OR scene.subject_id <> request.subject_id
                               OR scene.primary_party_id <> request.creator_party_id
                               OR (
                                   request.current_status IN ('granted', 'limited')
                                   AND permission.grant_id IS NULL
                               )
                               OR (
                                   request.current_status IN (
                                       'pending', 'denied', 'revoked', 'expired'
                                   )
                                   AND permission.grant_id IS NOT NULL
                                   AND permission.status = 'active'
                               )
                        )
                    FROM armi.capability_requests AS request
                    LEFT JOIN armi.capabilities AS capability
                      ON capability.capability_id = request.capability_id
                     AND capability.capability_kind = request.capability_kind
                     AND capability.operation_class = request.operation_class
                    LEFT JOIN armi.subject_commits AS commit
                      ON commit.subject_commit_id = request.subject_commit_id
                     AND commit.subject_id = request.subject_id
                    LEFT JOIN armi.interaction_scenes AS scene
                      ON scene.scene_id = request.interaction_scene_id
                    LEFT JOIN armi.permission_grants AS permission
                      ON permission.capability_request_id
                       = request.capability_request_id
                    """
                )
            ).fetchone()
            assert capability_counts is not None
            response_counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE response.phase = 'admission_pending'
                              AND response.outcome IS NULL
                        ),
                        count(*) FILTER (
                            WHERE opportunity.opportunity_id IS NULL
                               OR scene.scene_id IS NULL
                               OR scene.subject_id <> response.subject_id
                               OR scene.primary_party_id
                                  <> response.context_party_id
                               OR (
                                   response.phase = 'admission_pending'
                                   AND response.outcome IS NULL
                                   AND (
                                       intent.action_intent_id IS NULL
                                       OR revision.action_intent_revision_id
                                          IS NULL
                                       OR work.work_id IS NULL
                                       OR work.work_kind
                                          <> 'cognition.response.admit'
                                       OR work.status NOT IN ('ready', 'leased')
                                   )
                               )
                               OR (
                                   response.phase IN ('admitted', 'effect_registered', 'dispatching')
                                   AND response.outcome IS NULL
                                   AND (
                                       intent.action_intent_id IS NULL
                                       OR revision.action_intent_revision_id
                                          IS NULL
                                       OR response.matched_grant_id IS NULL
                                       OR work.status <> 'completed'
                                   )
                               )
                               OR (
                                   response.phase = 'terminal'
                                   AND response.outcome = 'no_action'
                                   AND no_action.dialogue_decision_id IS NULL
                               )
                               OR (
                                   response.phase = 'terminal'
                                   AND response.outcome IN ('denied', 'failed')
                                   AND (
                                       intent.action_intent_id IS NULL
                                       OR revision.action_intent_revision_id
                                          IS NULL
                                       OR work.status <> 'completed'
                                   )
                               )
                        )
                    FROM armi.action_operations AS response
                    LEFT JOIN armi.opportunities AS opportunity
                      ON opportunity.opportunity_id
                       = response.root_opportunity_id
                    LEFT JOIN armi.interaction_scenes AS scene
                      ON scene.scene_id = response.scene_id
                    LEFT JOIN armi.action_intents AS intent
                      ON intent.action_intent_id = response.action_intent_id
                    LEFT JOIN armi.action_intent_revisions AS revision
                      ON revision.action_intent_id = intent.action_intent_id
                     AND revision.action_intent_revision_id
                       = intent.current_revision_id
                    LEFT JOIN armi.dialogue_decisions AS no_action
                      ON no_action.dialogue_decision_id
                       = response.dialogue_decision_id
                    LEFT JOIN armi.durable_work AS work
                      ON work.work_id = response.admission_work_id
                    """
                )
            ).fetchone()
            assert response_counts is not None
            effect_counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*),
                        count(*) FILTER (WHERE outbox.effect_id IS NULL),
                        count(outbox.effect_id),
                        count(*) FILTER (
                            WHERE decision.policy_decision_id IS NULL
                               OR decision.decision_outcome <> 'allowed'
                               OR response.effect_id <> effect.effect_id
                               OR current_decision.policy_decision_id IS NULL
                               OR (
                                   effect.status = 'registered'
                                   AND (
                                       outbox.status <> 'ready'
                                       OR response.current_policy_decision_id
                                          <> decision.policy_decision_id
                                       OR NOT decision.is_current
                                   )
                               )
                               OR (
                                   effect.status = 'cancelled'
                                   AND (
                                       outbox.status <> 'cancelled'
                                       OR current_decision.decision_outcome
                                          <> 'denied'
                                       OR current_decision.supersedes_policy_decision_id
                                          <> decision.policy_decision_id
                                       OR NOT current_decision.is_current
                                       OR decision.is_current
                                   )
                               )
                        )
                    FROM armi.effects AS effect
                    LEFT JOIN armi.policy_decisions AS decision
                      ON decision.policy_decision_id = effect.policy_decision_id
                    LEFT JOIN armi.action_operations AS response
                      ON response.operation_id = effect.operation_id
                    LEFT JOIN armi.policy_decisions AS current_decision
                      ON current_decision.policy_decision_id =
                         response.current_policy_decision_id
                    LEFT JOIN armi.effect_outbox_items AS outbox
                      ON outbox.effect_id = effect.effect_id
                    """
                )
            ).fetchone()
            assert effect_counts is not None
            effect_execution_counts = await (
                await connection.execute(
                    """
                    SELECT
                        (SELECT count(*)
                         FROM armi.effect_attempts
                         WHERE dispatch_state IN ('prepared', 'dispatching')),
                        (SELECT count(*)
                         FROM armi.effect_observations
                         WHERE reliability = 'reliable'),
                        (SELECT count(*) FROM armi.local_inbox_deliveries),
                        count(*) FILTER (
                            WHERE
                                (effect.status = 'registered' AND outbox.status <> 'ready')
                                OR (effect.status = 'dispatching' AND (
                                    outbox.status <> 'claimed'
                                    OR attempt.dispatch_state <> 'dispatching'
                                    OR (
                                        effect.effect_kind = 'creator_response'
                                        AND (response.phase <> 'dispatching' OR response.outcome IS NOT NULL)
                                    )
                                    OR (
                                        effect.effect_kind = 'codex_delegation'
                                        AND (response.phase <> 'dispatching' OR response.outcome IS NOT NULL)
                                    )
                                ))
                                OR (
                                    effect.status = 'completed'
                                    AND effect.effect_kind = 'creator_response'
                                    AND (
                                    outbox.status <> 'delivered'
                                    OR attempt.result_status NOT IN ('succeeded', 'unknown')
                                    OR observation.reliability <> 'reliable'
                                    OR observation.observation_kind <> 'receipt'
                                    OR delivery.effect_id IS NULL
                                    OR observation.receiver_ref
                                       <> delivery.delivery_id
                                    OR response.phase <> 'terminal'
                                    OR response.outcome <> 'completed'
                                    )
                                )
                                OR (
                                    effect.status = 'completed'
                                    AND effect.effect_kind = 'codex_delegation'
                                    AND (
                                        outbox.status <> 'delivered'
                                        OR attempt.result_status <> 'succeeded'
                                        OR observation.reliability <> 'reliable'
                                        OR observation.observation_kind <> 'runner_verified'
                                        OR delivery.effect_id IS NOT NULL
                                        OR NOT (
                                            (response.phase = 'result_pending' AND response.outcome IS NULL)
                                            OR (response.phase = 'terminal' AND response.outcome IN ('completed', 'rejected'))
                                        )
                                    )
                                )
                                OR (effect.status = 'failed' AND (
                                    outbox.status <> 'dead'
                                    OR attempt.result_status NOT IN ('failed', 'unknown')
                                    OR observation.reliability <> 'reliable'
                                    OR (
                                        effect.effect_kind = 'creator_response'
                                        AND (response.phase <> 'terminal' OR response.outcome <> 'failed')
                                    )
                                    OR (
                                        effect.effect_kind = 'codex_delegation'
                                        AND (
                                            observation.observation_kind
                                                <> 'runner_failed'
                                            OR response.phase <> 'terminal'
                                            OR response.outcome <> 'failed'
                                        )
                                    )
                                ))
                                OR (effect.status = 'unknown' AND (
                                    outbox.status <> 'unknown'
                                    OR attempt.result_status <> 'unknown'
                                    OR observation.reliability <> 'inconclusive'
                                    OR (
                                        effect.effect_kind = 'creator_response'
                                        AND (response.phase <> 'terminal' OR response.outcome <> 'unknown')
                                    )
                                    OR (
                                        effect.effect_kind = 'codex_delegation'
                                        AND (
                                            observation.observation_kind
                                                <> 'runner_unknown'
                                            OR response.phase <> 'terminal'
                                            OR response.outcome <> 'unknown'
                                        )
                                    )
                                ))
                                OR (effect.status = 'cancelled' AND (
                                    outbox.status <> 'cancelled'
                                    OR (
                                        effect.effect_kind = 'creator_response'
                                        AND (response.phase <> 'terminal' OR response.outcome <> 'cancelled')
                                    )
                                    OR (
                                        effect.effect_kind = 'codex_delegation'
                                        AND (
                                            observation.observation_kind
                                                <> 'runner_cancelled'
                                            OR response.phase <> 'terminal'
                                            OR response.outcome <> 'cancelled'
                                        )
                                    )
                                ))
                        )
                    FROM armi.effects AS effect
                    JOIN armi.effect_outbox_items AS outbox
                      ON outbox.effect_id = effect.effect_id
                    JOIN armi.action_operations AS response
                      ON response.operation_id
                       = effect.operation_id
                    LEFT JOIN armi.effect_attempts AS attempt
                      ON attempt.effect_attempt_id = effect.current_attempt_id
                     AND attempt.effect_id = effect.effect_id
                    LEFT JOIN armi.effect_observations AS observation
                      ON observation.effect_observation_id
                       = effect.current_observation_id
                     AND observation.effect_id = effect.effect_id
                     AND observation.effect_attempt_id = attempt.effect_attempt_id
                    LEFT JOIN armi.local_inbox_deliveries AS delivery
                      ON delivery.effect_id = effect.effect_id
                    """
                )
            ).fetchone()
            assert effect_execution_counts is not None
            await connection.execute(
                """
                UPDATE armi.observation_attempts AS attempt
                SET dispatch_state = 'settled', result_status = 'cancelled',
                    error_code = 'WEB-RECOVERY-PRE-DISPATCH',
                    settled_at = statement_timestamp()
                FROM armi.web_observation_requests AS request,
                     armi.durable_work AS work
                WHERE attempt.web_observation_request_id
                      = request.web_observation_request_id
                  AND request.work_id = work.work_id
                  AND attempt.dispatch_state = 'prepared'
                  AND work.status = 'ready'
                """
            )
            await connection.execute(
                """
                UPDATE armi.observation_attempts
                SET dispatch_state = 'settled',
                    result_status = 'outcome_unknown',
                    error_code = 'WEB-RECOVERY-OUTCOME-UNKNOWN',
                    settled_at = statement_timestamp()
                WHERE dispatch_state = 'dispatched'
                """
            )
            await connection.execute(
                """
                UPDATE armi.web_observation_requests AS request
                SET status = 'unknown',
                    last_error_code = 'WEB-RECOVERY-OUTCOME-UNKNOWN',
                    completed_at = statement_timestamp()
                WHERE request.status IN ('pending', 'running')
                  AND EXISTS (
                      SELECT 1 FROM armi.observation_attempts AS attempt
                      WHERE attempt.web_observation_request_id
                            = request.web_observation_request_id
                        AND attempt.result_status = 'outcome_unknown'
                  )
                """
            )
            await connection.execute(
                """
                UPDATE armi.durable_work AS work
                SET status = 'failed', current_attempt_id = NULL,
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error_code = 'WEB-RECOVERY-OUTCOME-UNKNOWN'
                FROM armi.web_observation_requests AS request
                WHERE request.work_id = work.work_id
                  AND request.status = 'unknown'
                  AND work.status IN ('ready', 'leased')
                """
            )
            web_counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE request.status IN ('pending', 'running')
                        ),
                        (SELECT count(*) FROM armi.observation_attempts
                         WHERE result_status = 'outcome_unknown'),
                        count(*) FILTER (
                            WHERE (request.status IN ('pending', 'running')
                                   AND work.status NOT IN ('ready', 'leased'))
                               OR (request.status = 'succeeded' AND (
                                   request.result_artifact_id IS NULL
                                   OR request.result_digest IS NULL
                                   OR work.status <> 'completed'
                               ))
                               OR (request.status = 'unknown' AND NOT EXISTS (
                                   SELECT 1
                                   FROM armi.observation_attempts AS attempt
                                   WHERE attempt.web_observation_request_id
                                         = request.web_observation_request_id
                                     AND attempt.result_status
                                         = 'outcome_unknown'
                               ))
                        )
                    FROM armi.web_observation_requests AS request
                    JOIN armi.durable_work AS work
                      ON work.work_id = request.work_id
                    """
                )
            ).fetchone()
            assert web_counts is not None
            web_evidence_counts = await (
                await connection.execute(
                    """
                    SELECT
                        count(*) FILTER (
                            WHERE intent.status IN ('pending', 'admitted')
                        ),
                        count(*) FILTER (
                            WHERE intent.status = 'admitted'
                              AND request.status IN ('pending', 'running')
                        ),
                        (SELECT count(*)
                         FROM armi.opportunities
                         WHERE purpose = 'consider_web_evidence'
                           AND current_disposition IN ('open', 'selected')),
                        count(*) FILTER (
                            WHERE (intent.status = 'pending' AND (
                                work.status NOT IN ('ready', 'leased')
                                OR intent.web_observation_request_id IS NOT NULL
                            ))
                            OR (intent.status = 'admitted' AND (
                                intent.web_observation_request_id IS NULL
                                OR request.web_research_intent_id
                                   IS DISTINCT FROM intent.web_research_intent_id
                            ))
                            OR (intent.status = 'succeeded' AND NOT EXISTS (
                                SELECT 1
                                FROM armi.external_evidence AS evidence
                                WHERE evidence.web_observation_request_id
                                      = intent.web_observation_request_id
                                  AND evidence.source_kind = 'web_search'
                            ))
                        )
                    FROM armi.web_research_intents AS intent
                    JOIN armi.durable_work AS work
                      ON work.work_id = intent.admission_work_id
                    LEFT JOIN armi.web_observation_requests AS request
                      ON request.web_observation_request_id
                         = intent.web_observation_request_id
                    """
                )
            ).fetchone()
            assert web_evidence_counts is not None
            codex_counts = await (
                await connection.execute(
                    """
                    SELECT
                        (SELECT count(*)
                         FROM armi.opportunities
                         WHERE purpose='consider_codex_task'
                           AND current_disposition IN ('open', 'selected')),
                        (SELECT count(*)
                         FROM armi.effects
                         WHERE effect_kind='codex_delegation'
                           AND status IN ('registered', 'dispatching', 'unknown')),
                        (SELECT count(*)
                         FROM armi.opportunities
                         WHERE purpose='consider_codex_result'
                           AND current_disposition IN ('open', 'selected')),
                        (SELECT count(*)
                         FROM armi.codex_result_sources AS source
                         JOIN armi.codex_verification_results AS verification
                           ON verification.codex_verification_id=source.codex_verification_id
                         JOIN armi.effects AS effect ON effect.effect_id=verification.effect_id
                         WHERE (effect.status='completed'
                                AND verification.execution_status<>'verified')
                            OR (effect.status IN ('failed','unknown','cancelled')
                                AND verification.execution_status='verified'))
                    """
                )
            ).fetchone()
            assert codex_counts is not None
            admin_correction_work_count = await (
                await connection.execute(
                    """
                    SELECT count(*)
                    FROM armi.durable_work AS work
                    JOIN armi.outbox_items AS outbox
                      ON outbox.work_id = work.work_id
                     AND outbox.message_kind = 'admin.correction.available'
                    WHERE work.work_kind = 'admin.correction.artifact-cleanup'
                      AND work.owner_kind = 'admin_correction'
                      AND work.status = 'ready'
                      AND outbox.status = 'ready'
                    """
                )
            ).fetchone()
            assert admin_correction_work_count is not None
            if int(counts[7]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "opportunity",
                                RecoveryDecision.BLOCKED,
                                "REC-OPPORTUNITY-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if int(capability_counts[1]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "capability_request",
                                RecoveryDecision.BLOCKED,
                                "REC-CAPABILITY-REQUEST-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if int(response_counts[1]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "response_operation",
                                RecoveryDecision.BLOCKED,
                                "REC-RESPONSE-OPERATION-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if (
                int(effect_counts[1]) > 0
                or int(effect_counts[3]) > 0
                or int(effect_execution_counts[3]) > 0
            ):
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "effect", RecoveryDecision.BLOCKED, "REC-EFFECT-INVALID"
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if int(web_counts[2]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "web_observation",
                                RecoveryDecision.BLOCKED,
                                "REC-WEB-OBSERVATION-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if int(web_evidence_counts[3]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "web_evidence",
                                RecoveryDecision.BLOCKED,
                                "REC-WEB-EVIDENCE-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            if int(codex_counts[3]) > 0:
                blockers += 1
                sorted_findings = tuple(
                    sorted(
                        (
                            *sorted_findings,
                            RecoveryFinding(
                                "codex_delegation",
                                RecoveryDecision.BLOCKED,
                                "REC-CODEX-DELEGATION-INVALID",
                            ),
                        ),
                        key=_finding_key,
                    )
                )
            status = (
                RecoveryStatus.SAFE
                if blockers == 0 and critical == 2
                else RecoveryStatus.BLOCKED
            )
            if critical != 2 and blockers == 0:
                blockers = 1
                sorted_findings = (
                    *sorted_findings,
                    RecoveryFinding(
                        "critical_artifact",
                        RecoveryDecision.BLOCKED,
                        "REC-ARTIFACT-COUNT",
                    ),
                )
            semantic = {
                "status": status.value,
                "requeued_work": scan.requeued_work,
                "terminal_work": scan.terminal_work,
                "requeued_outbox": scan.requeued_outbox,
                "dead_outbox": scan.dead_outbox,
                "resumable_work": int(counts[0]),
                "resumable_outbox": int(counts[1]),
                "resumable_opportunity": int(counts[2]),
                "resumable_cognitive_episode": int(counts[3]),
                "resumable_model_attempt": int(counts[5]),
                "resumable_candidate_validation": int(counts[4]),
                "resumable_subject_commit": int(counts[6]),
                "resumable_capability_request": int(capability_counts[0]),
                "resumable_response_operation": int(response_counts[0]),
                "resumable_effect": int(effect_counts[0]),
                "resumable_effect_outbox": int(effect_counts[2]),
                "resumable_effect_attempt": int(effect_execution_counts[0]),
                "reliable_effect_observation": int(effect_execution_counts[1]),
                "creator_response_delivery": int(effect_execution_counts[2]),
                "resumable_web_observation": int(web_counts[0]),
                "unknown_web_observation_attempt": int(web_counts[1]),
                "resumable_web_research_intent": int(web_evidence_counts[0]),
                "pending_web_evidence_acceptance": int(web_evidence_counts[1]),
                "resumable_web_cognition": int(web_evidence_counts[2]),
                "resumable_codex_task": int(codex_counts[0]),
                "resumable_codex_effect": int(codex_counts[1]),
                "pending_codex_result_acceptance": int(codex_counts[2]),
                "resumable_admin_correction_work": int(admin_correction_work_count[0]),
                "critical_artifacts": critical,
                "blockers": blockers,
                "findings": [
                    {
                        "kind": value.kind,
                        "decision": value.decision.value,
                        "reason": value.reason_code,
                        "reference": (
                            None if value.reference is None else str(value.reference)
                        ),
                    }
                    for value in sorted_findings
                ],
            }
            digest = _summary_digest(semantic)
            metrics = {
                "requeued_work_count": scan.requeued_work,
                "terminal_work_count": scan.terminal_work,
                "requeued_outbox_count": scan.requeued_outbox,
                "dead_outbox_count": scan.dead_outbox,
                "resumable_work_count": int(counts[0]),
                "resumable_outbox_count": int(counts[1]),
                "resumable_opportunity_count": int(counts[2]),
                "resumable_cognitive_episode_count": int(counts[3]),
                "resumable_model_attempt_count": int(counts[5]),
                "resumable_candidate_validation_count": int(counts[4]),
                "resumable_subject_commit_count": int(counts[6]),
                "resumable_capability_request_count": int(capability_counts[0]),
                "resumable_response_operation_count": int(response_counts[0]),
                "resumable_effect_count": int(effect_counts[0]),
                "resumable_effect_outbox_count": int(effect_counts[2]),
                "resumable_effect_attempt_count": int(effect_execution_counts[0]),
                "reliable_effect_observation_count": int(effect_execution_counts[1]),
                "creator_response_delivery_count": int(effect_execution_counts[2]),
                "resumable_web_observation_count": int(web_counts[0]),
                "unknown_web_observation_attempt_count": int(web_counts[1]),
                "resumable_web_research_intent_count": int(web_evidence_counts[0]),
                "pending_web_evidence_acceptance_count": int(web_evidence_counts[1]),
                "resumable_web_cognition_count": int(web_evidence_counts[2]),
                "resumable_admin_correction_work_count": int(
                    admin_correction_work_count[0]
                ),
                "resumable_codex_task_count": int(codex_counts[0]),
                "resumable_codex_effect_count": int(codex_counts[1]),
                "pending_codex_result_acceptance_count": int(codex_counts[2]),
                "critical_artifact_count": critical,
            }
            updated = await connection.execute(
                """
                UPDATE armi.runtime_recovery_runs
                SET status = %s,
                    completed_at = statement_timestamp(),
                    blocker_count = %s,
                    summary_digest = %s
                WHERE recovery_run_id = %s
                  AND status = 'running'
                """,
                (
                    status.value,
                    blockers,
                    digest.value,
                    scan.recovery_run_id,
                ),
            )
            if updated.rowcount != 1:
                raise RecoveryViolation("REC-RUN-STALE")
            async with connection.cursor() as metric_cursor:
                await metric_cursor.executemany(
                    """UPDATE armi.runtime_recovery_metrics SET metric_value = %s
                       WHERE recovery_run_id = %s AND metric_kind = %s""",
                    tuple(
                        (metrics[kind], scan.recovery_run_id, kind)
                        for kind in _RECOVERY_METRIC_KINDS
                    ),
                )
                metric_rowcount = metric_cursor.rowcount
            if metric_rowcount != len(_RECOVERY_METRIC_KINDS):
                raise RecoveryViolation("REC-METRIC-SET")
            await self._validate_metric_set(connection, scan.recovery_run_id)
            await PostgreSQLAuditWriter(connection).append(
                _audit(
                    fence,
                    f"runtime.recovery.{status.value}",
                    scan.recovery_run_id,
                )
            )
            await self._verify_fence(connection, fence)
        return RecoverySummary(
            recovery_run_id=RecoveryRunId(scan.recovery_run_id),
            status=status,
            requeued_work_count=scan.requeued_work,
            terminal_work_count=scan.terminal_work,
            requeued_outbox_count=scan.requeued_outbox,
            dead_outbox_count=scan.dead_outbox,
            resumable_work_count=int(counts[0]),
            resumable_outbox_count=int(counts[1]),
            resumable_opportunity_count=int(counts[2]),
            resumable_cognitive_episode_count=int(counts[3]),
            resumable_model_attempt_count=int(counts[5]),
            resumable_candidate_validation_count=int(counts[4]),
            resumable_subject_commit_count=int(counts[6]),
            resumable_capability_request_count=int(capability_counts[0]),
            resumable_response_operation_count=int(response_counts[0]),
            resumable_effect_count=int(effect_counts[0]),
            resumable_effect_outbox_count=int(effect_counts[2]),
            resumable_effect_attempt_count=int(effect_execution_counts[0]),
            reliable_effect_observation_count=int(effect_execution_counts[1]),
            creator_response_delivery_count=int(effect_execution_counts[2]),
            resumable_web_observation_count=int(web_counts[0]),
            unknown_web_observation_attempt_count=int(web_counts[1]),
            critical_artifact_count=critical,
            blocker_count=blockers,
            summary_digest=digest,
            findings=tuple(sorted_findings),
            resumable_web_research_intent_count=int(web_evidence_counts[0]),
            pending_web_evidence_acceptance_count=int(web_evidence_counts[1]),
            resumable_web_cognition_count=int(web_evidence_counts[2]),
            resumable_admin_correction_work_count=int(admin_correction_work_count[0]),
            resumable_codex_task_count=int(codex_counts[0]),
            resumable_codex_effect_count=int(codex_counts[1]),
            pending_codex_result_acceptance_count=int(codex_counts[2]),
        )

    async def _record_artifact_failures(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        fence: RuntimeFence,
        findings: tuple[RecoveryFinding, ...],
    ) -> None:
        writer = PostgreSQLAuditWriter(connection)
        for finding in findings:
            if (
                finding.kind != "critical_artifact"
                or finding.reference is None
                or finding.reason_code
                not in {"REC-ARTIFACT-MISSING", "REC-ARTIFACT-CORRUPT"}
            ):
                continue
            status = (
                "missing"
                if finding.reason_code == "REC-ARTIFACT-MISSING"
                else "corrupt"
            )
            row = await (
                await connection.execute(
                    """
                    UPDATE armi.artifacts
                    SET integrity_status = %s
                    WHERE artifact_id = %s
                      AND integrity_status = 'verified'
                    RETURNING artifact_id
                    """,
                    (status, finding.reference),
                )
            ).fetchone()
            if row is not None:
                await writer.append(
                    _audit(
                        fence,
                        f"artifact.integrity.{status}",
                        finding.reference,
                    )
                )

    async def _verify_fence(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        fence: RuntimeFence,
    ) -> None:
        row = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.runtime_instances AS instance
                JOIN armi.subjects AS subject
                  ON subject.subject_id = instance.subject_id
                WHERE instance.runtime_instance_id = %s
                  AND instance.fence_token = %s
                  AND instance.status = 'active'
                  AND instance.lease_expires_at > statement_timestamp()
                  AND subject.singleton_key = 1
                  AND subject.current_generation_id = instance.life_generation_id
                  AND subject.current_bundle_activation_id
                    = instance.bundle_activation_id
                FOR UPDATE OF instance
                """,
                (fence.runtime_instance_id.value, fence.fence_token),
            )
        ).fetchone()
        if row is None:
            raise RecoveryViolation("REC-FENCE-STALE")

    def _require_fence(self) -> RuntimeFence:
        try:
            fence = self._admission()
        except RuntimeAuthorityViolation as error:
            code = (
                "REC-AUTHORITY-SUSPENDED"
                if error.code == "AUTH-LOCAL-SUSPENDED"
                else "REC-FENCE-STALE"
            )
            raise RecoveryViolation(code) from None
        if type(fence) is not RuntimeFence:
            raise RecoveryViolation("REC-FENCE-STALE")
        return fence


def _artifact_ref(row: tuple[Any, ...]) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=ArtifactId(row[0]),
        content_digest=Digest(str(row[1])),
        byte_size=int(row[2]),
        media_type=str(row[3]),
        logical_kind=str(row[4]),
        privacy_scope=ArtifactPrivacyScope(str(row[5])),
        integrity_status=ArtifactIntegrityStatus(str(row[6])),
    )


def _finding_key(value: RecoveryFinding) -> tuple[str, str, str, str]:
    return (
        value.kind,
        value.decision.value,
        value.reason_code,
        "" if value.reference is None else str(value.reference),
    )


def _summary_digest(value: object) -> Digest:
    return Digest(
        "sha256:" + hashlib.sha256(rfc8785.dumps(cast(Any, value))).hexdigest()
    )


def _audit(
    fence: RuntimeFence,
    operation: str,
    target_ref: UUID,
) -> AuditDraft:
    target_kind = (
        "durable_work"
        if operation.startswith("work.")
        else "outbox"
        if operation.startswith("outbox.")
        else "artifact"
        if operation.startswith("artifact.")
        else "recovery"
    )
    return AuditDraft(
        audit_event_id=AuditEventId(uuid7()),
        actor=AuditReference("runtime", fence.runtime_instance_id.value),
        purpose=Purpose("runtime.recovery"),
        operation=operation,
        target=AuditReference(target_kind, target_ref),
        result_status=AuditResultStatus.APPLIED,
        trace_id=TraceId(fence.runtime_instance_id.value.hex),
        sensitivity=AuditSensitivity.INTERNAL,
        subject_id=SubjectId(fence.subject_id),
    )


__all__ = ("PostgreSQLRuntimeRecovery",)
