"""Fenced startup recovery coordinated through owner participants."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    RecoveryDecision,
    RecoveryFinding,
    RecoveryMetric,
    RecoveryRunId,
    RecoveryStatus,
    RecoverySummary,
    RecoveryViolation,
    RuntimeAuthorityViolation,
    RuntimeFence,
    TransactionIsolation,
)
from armi_kernel.contracts import Purpose, SubjectId, TraceId
from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryAuditContribution,
    RecoveryContribution,
    RecoveryDependentParticipant,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryParticipant,
    RecoveryScope,
    RecoveryWorkCommand,
    RecoveryWorkCommandKind,
    RecoveryWorkSnapshot,
    RuntimeTransactionFailure,
)

from .unit_of_work import PostgreSQLUnitOfWorkFactory


class PostgreSQLRuntimeRecovery:
    """Own Runtime recovery facts and coordinate fixed owner participants."""

    __slots__ = (
        "_admission",
        "_catalog",
        "_environment_id",
        "_expected_owners",
        "_factory",
        "_participants",
        "_storage",
    )

    def __init__(
        self,
        factory: PostgreSQLUnitOfWorkFactory,
        *,
        environment_id: UUID,
        data_root: Path,
        max_object_bytes: int,
        authority_admission: Callable[[], RuntimeFence],
        participants: tuple[RecoveryParticipant, ...],
        expected_owners: tuple[RecoveryOwnerIdentity, ...],
        catalog: ArtifactCatalogPort,
    ) -> None:
        self._environment_id = environment_id
        self._factory = factory
        self._admission = authority_admission
        self._participants = participants
        self._expected_owners = expected_owners
        self._catalog = catalog
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        )
        self._validate_roster()

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise RecoveryViolation("REC-DEPENDENCY") from None

    async def close(self) -> None:
        return None

    async def recover(self) -> RecoverySummary:
        fence = self._require_fence()
        scope = RecoveryScope(
            self._environment_id,
            fence.subject_id,
            fence.life_generation_id,
            fence.bundle_activation_id,
            fence.runtime_instance_id.value,
            fence.fence_token,
        )
        try:
            run_id, contributions, refs = await self._recover_owners(fence, scope)
            artifact_contribution = await self._verify_artifacts(refs)
            return await self._finalize(
                fence, run_id, (*contributions, artifact_contribution)
            )
        except RecoveryViolation:
            raise
        except RuntimeTransactionFailure, ValueError:
            raise RecoveryViolation("REC-DATABASE") from None

    def _validate_roster(self) -> None:
        actual = tuple(participant.owner_identity for participant in self._participants)
        if actual != self._expected_owners or len(set(actual)) != len(actual):
            raise RecoveryViolation("REC-PARTICIPANT-ROSTER")

    async def _recover_owners(
        self, fence: RuntimeFence, scope: RecoveryScope
    ) -> tuple[UUID, tuple[RecoveryContribution, ...], tuple[ArtifactRef, ...]]:
        async with self._factory.unit_of_work(
            isolation=TransactionIsolation.SERIALIZABLE
        ) as unit:
            transaction = unit.transaction
            await self._verify_fence(transaction, fence)
            await self._abandon_old_runs(transaction, fence)
            run_id = await self._running_row(transaction, fence)
            runtime = await self._recover_runtime_work(transaction, scope)
            snapshots = await self._work_snapshots(transaction)
            contributions: list[RecoveryContribution] = [runtime]
            for participant in self._participants:
                selected = tuple(
                    item
                    for item in snapshots
                    if (item.owner_kind, item.work_kind) in participant.work_scopes
                )
                if isinstance(participant, RecoveryDependentParticipant):
                    contribution = await participant.recover_with_prior(
                        transaction, scope, selected, tuple(contributions)
                    )
                else:
                    contribution = await participant.recover(
                        transaction, scope, selected
                    )
                self._validate_contribution(participant, contribution)
                contributions.append(contribution)
            artifact_ids = tuple(
                artifact_id
                for contribution in contributions
                for artifact_id in contribution.critical_artifact_ids
            )
            if len(set(artifact_ids)) != len(artifact_ids):
                raise RecoveryViolation("REC-ARTIFACT-DUPLICATE")
            refs: list[ArtifactRef] = []
            for artifact_id in artifact_ids:
                ref = await self._catalog.retained_ref_in(
                    transaction, ArtifactId(artifact_id)
                )
                if ref is None:
                    contributions.append(
                        RecoveryContribution(
                            RecoveryOwnerIdentity("artifact-store"),
                            findings=(
                                _finding(
                                    "critical_artifact",
                                    RecoveryFindingDecision.BLOCKED,
                                    "REC-ARTIFACT-MISSING",
                                    artifact_id,
                                ),
                            ),
                        )
                    )
                else:
                    refs.append(ref)
            for contribution in contributions:
                for command in contribution.work_commands:
                    await self._apply_work_command(transaction, command)
                for audit in contribution.audits:
                    await unit.audit.append(_owner_audit(fence, audit))
            await unit.audit.append(
                _runtime_audit(fence, "runtime.recovery.started", run_id)
            )
            await self._verify_fence(transaction, fence)
            return run_id, tuple(contributions), tuple(refs)

    async def _recover_runtime_work(
        self, transaction: PostgreSQLTransaction, scope: RecoveryScope
    ) -> RecoveryContribution:
        rows = await (
            await transaction.execute(
                """
                UPDATE armi.durable_work
                SET status = CASE
                        WHEN attempt_count < max_attempts THEN 'ready'
                        ELSE 'failed'
                    END,
                    current_attempt_id = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = CASE
                        WHEN attempt_count < max_attempts THEN 'WORK-LEASE-EXPIRED'
                        ELSE 'WORK-ATTEMPTS-EXHAUSTED'
                    END,
                    updated_at = clock_timestamp()
                WHERE status = 'leased'
                  AND lease_expires_at <= statement_timestamp()
                RETURNING status
                """
            )
        ).fetchall()
        continuity = await (
            await transaction.execute(
                """
                SELECT count(*)
                FROM armi.subjects AS subject
                JOIN armi.life_generations AS generation
                  ON generation.life_generation_id = subject.current_generation_id
                 AND generation.subject_id = subject.subject_id
                 AND generation.status = 'active'
                JOIN armi.runtime_bundle_activations AS activation
                  ON activation.bundle_activation_id
                   = subject.current_bundle_activation_id
                 AND activation.status = 'current'
                WHERE subject.singleton_key = 1
                  AND subject.status = 'active'
                  AND subject.subject_id = %s
                  AND subject.current_generation_id = %s
                  AND subject.current_bundle_activation_id = %s
                """,
                (
                    scope.subject_id,
                    scope.life_generation_id,
                    scope.bundle_activation_id,
                ),
            )
        ).fetchone()
        requeued = sum(str(row[0]) == "ready" for row in rows)
        terminal = sum(str(row[0]) == "failed" for row in rows)
        findings = ()
        if continuity is None or int(continuity[0]) != 1:
            findings = (
                _finding(
                    "subject_continuity",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-SUBJECT-INVALID",
                ),
            )
        return RecoveryContribution(
            RecoveryOwnerIdentity("runtime"),
            findings=findings,
            metrics=(
                _metric("runtime.requeued_work_count", requeued),
                _metric("runtime.terminal_work_count", terminal),
            ),
        )

    async def _work_snapshots(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[RecoveryWorkSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT work_id, work_kind, owner_kind, owner_ref, status,
                       attempt_count, max_attempts, payload_kind, payload_ref,
                       payload_digest
                FROM armi.durable_work
                ORDER BY work_id
                """
            )
        ).fetchall()
        return tuple(
            RecoveryWorkSnapshot(
                row[0],
                str(row[1]),
                str(row[2]),
                row[3],
                str(row[4]),
                int(row[5]),
                int(row[6]),
                None if row[7] is None else str(row[7]),
                row[8],
                None if row[9] is None else str(row[9]),
            )
            for row in rows
        )

    def _validate_contribution(
        self, participant: RecoveryParticipant, value: RecoveryContribution
    ) -> None:
        if value.owner != participant.owner_identity:
            raise RecoveryViolation("REC-PARTICIPANT-IDENTITY")
        prefix = value.owner.value.replace("-", "_") + "."
        if any(not metric.kind.startswith(prefix) for metric in value.metrics):
            raise RecoveryViolation("REC-PARTICIPANT-METRIC")

    async def _apply_work_command(
        self, transaction: PostgreSQLTransaction, command: RecoveryWorkCommand
    ) -> None:
        if command.kind is RecoveryWorkCommandKind.ENQUEUE:
            raise RecoveryViolation("REC-WORK-COMMAND")
        target = (
            "failed" if command.kind is RecoveryWorkCommandKind.FAIL else "cancelled"
        )
        result = await transaction.execute(
            """
            UPDATE armi.durable_work
            SET status = %s, current_attempt_id = NULL, lease_owner = NULL,
                lease_expires_at = NULL, last_error_code = %s,
                updated_at = clock_timestamp()
            WHERE work_id = %s AND work_kind = %s
              AND owner_kind = %s AND owner_ref = %s
              AND status IN ('ready', 'leased')
            """,
            (
                target,
                command.reason_code,
                command.work_id,
                command.work_kind,
                command.owner_kind,
                command.owner_ref,
            ),
        )
        if result.rowcount != 1:
            raise RecoveryViolation("REC-WORK-COMMAND")

    async def _verify_artifacts(
        self, refs: tuple[ArtifactRef, ...]
    ) -> RecoveryContribution:
        findings: list[RecoveryFindingContribution] = []
        for ref in refs:
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
                    _finding(
                        "critical_artifact",
                        RecoveryFindingDecision.BLOCKED,
                        reason,
                        ref.artifact_id.value,
                    )
                )
            else:
                findings.append(
                    _finding(
                        "critical_artifact",
                        RecoveryFindingDecision.VERIFIED,
                        "REC-ARTIFACT-VERIFIED",
                        ref.artifact_id.value,
                    )
                )
        return RecoveryContribution(
            RecoveryOwnerIdentity("artifact-store"),
            findings=tuple(findings),
            metrics=(
                _metric(
                    "artifact_store.verified_critical_count",
                    sum(
                        item.decision is RecoveryFindingDecision.VERIFIED
                        for item in findings
                    ),
                ),
            ),
        )

    async def _finalize(
        self,
        fence: RuntimeFence,
        run_id: UUID,
        contributions: tuple[RecoveryContribution, ...],
    ) -> RecoverySummary:
        findings = tuple(
            sorted(
                (item for value in contributions for item in value.findings),
                key=lambda item: (
                    item.kind,
                    item.reason_code,
                    str(item.reference or ""),
                ),
            )
        )
        metrics = tuple(
            sorted(
                (item for value in contributions for item in value.metrics),
                key=lambda item: item.kind,
            )
        )
        if len({metric.kind for metric in metrics}) != len(metrics):
            raise RecoveryViolation("REC-METRIC-SET")
        blockers = sum(
            item.decision is RecoveryFindingDecision.BLOCKED for item in findings
        )
        status = RecoveryStatus.SAFE if blockers == 0 else RecoveryStatus.BLOCKED
        async with self._factory.unit_of_work(
            isolation=TransactionIsolation.SERIALIZABLE
        ) as unit:
            transaction = unit.transaction
            await self._verify_fence(transaction, fence)
            for finding in findings:
                if finding.reference is None or finding.reason_code not in {
                    "REC-ARTIFACT-MISSING",
                    "REC-ARTIFACT-CORRUPT",
                }:
                    continue
                await self._catalog.mark_integrity(
                    unit,
                    _artifact_id(finding.reference),
                    ArtifactIntegrityStatus.MISSING
                    if finding.reason_code == "REC-ARTIFACT-MISSING"
                    else ArtifactIntegrityStatus.CORRUPT,
                )
            for metric in metrics:
                await transaction.execute(
                    """
                    INSERT INTO armi.runtime_recovery_metrics
                        (recovery_run_id, metric_kind, metric_value)
                    VALUES (%s, %s, %s)
                    """,
                    (run_id, metric.kind, metric.value),
                )
            result = await transaction.execute(
                """
                UPDATE armi.runtime_recovery_runs
                SET status = %s, completed_at = statement_timestamp(),
                    blocker_count = %s
                WHERE recovery_run_id = %s AND status = 'running'
                """,
                (status.value, blockers, run_id),
            )
            if result.rowcount != 1:
                raise RecoveryViolation("REC-RUN-STALE")
            await unit.audit.append(
                _runtime_audit(fence, f"runtime.recovery.{status.value}", run_id)
            )
        return RecoverySummary(
            RecoveryRunId(run_id),
            status,
            tuple(RecoveryMetric(item.kind, item.value) for item in metrics),
            blockers,
            tuple(
                RecoveryFinding(
                    item.kind,
                    RecoveryDecision(item.decision.value),
                    item.reason_code,
                    item.reference,
                )
                for item in findings
            ),
        )

    async def _abandon_old_runs(
        self, transaction: PostgreSQLTransaction, fence: RuntimeFence
    ) -> None:
        await transaction.execute(
            """
            UPDATE armi.runtime_recovery_runs AS run
            SET status = 'abandoned', completed_at = statement_timestamp(),
                blocker_count = 1
            FROM armi.runtime_instances AS instance
            WHERE instance.runtime_instance_id = run.runtime_instance_id
              AND run.status = 'running'
              AND run.runtime_instance_id <> %s
              AND instance.status IN ('fenced', 'stopped')
            """,
            (fence.runtime_instance_id.value,),
        )

    async def _running_row(
        self, transaction: PostgreSQLTransaction, fence: RuntimeFence
    ) -> UUID:
        row = await (
            await transaction.execute(
                """
                SELECT recovery_run_id, status FROM armi.runtime_recovery_runs
                WHERE runtime_instance_id = %s FOR UPDATE
                """,
                (fence.runtime_instance_id.value,),
            )
        ).fetchone()
        if row is not None:
            if str(row[1]) != "running":
                raise RecoveryViolation("REC-ALREADY-COMPLETED")
            return row[0]
        run_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.runtime_recovery_runs (
                recovery_run_id, runtime_instance_id, subject_id,
                life_generation_id, bundle_activation_id, fence_token, status)
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
        return run_id

    async def _verify_fence(
        self, transaction: PostgreSQLTransaction, fence: RuntimeFence
    ) -> None:
        row = await (
            await transaction.execute(
                """
                SELECT status, lease_expires_at > statement_timestamp()
                FROM armi.runtime_instances
                WHERE runtime_instance_id = %s AND subject_id = %s
                  AND life_generation_id = %s AND bundle_activation_id = %s
                  AND fence_token = %s
                """,
                (
                    fence.runtime_instance_id.value,
                    fence.subject_id,
                    fence.life_generation_id,
                    fence.bundle_activation_id,
                    fence.fence_token,
                ),
            )
        ).fetchone()
        if row is None or str(row[0]) != "active" or not bool(row[1]):
            raise RecoveryViolation("REC-FENCE-STALE")

    def _require_fence(self) -> RuntimeFence:
        try:
            fence = self._admission()
        except RuntimeAuthorityViolation:
            raise RecoveryViolation("REC-FENCE-STALE") from None
        return fence


def _finding(
    kind: str,
    decision: RecoveryFindingDecision,
    reason: str,
    reference: UUID | None = None,
) -> RecoveryFindingContribution:
    return RecoveryFindingContribution(kind, decision, reason, reference)


def _metric(kind: str, value: int) -> RecoveryMetricContribution:
    return RecoveryMetricContribution(kind, value)


def _artifact_id(value: UUID) -> ArtifactId:
    return ArtifactId(value)


def _runtime_audit(fence: RuntimeFence, operation: str, target: UUID) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", fence.runtime_instance_id.value),
        Purpose("runtime.recovery"),
        operation,
        AuditReference("recovery", target),
        AuditResultStatus.COMPLETED,
        TraceId(fence.runtime_instance_id.value.hex),
        AuditSensitivity.PRIVATE,
        subject_id=SubjectId(fence.subject_id),
    )


def _owner_audit(fence: RuntimeFence, value: RecoveryAuditContribution) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", fence.runtime_instance_id.value),
        Purpose("runtime.recovery"),
        value.operation,
        AuditReference(value.target_kind, value.target_ref),
        AuditResultStatus.COMPLETED,
        TraceId(fence.runtime_instance_id.value.hex),
        AuditSensitivity.PRIVATE,
        subject_id=SubjectId(fence.subject_id),
    )


__all__ = ("PostgreSQLRuntimeRecovery",)
