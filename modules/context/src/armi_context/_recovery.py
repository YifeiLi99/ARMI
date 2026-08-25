"""Context-owned reconciliation of exact-query and embedding responsibility."""

from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_runtime_foundation import (
    OwnerReconciliationContext,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)

from ._embedding import EMBEDDING_BINDING_ID


class ContextRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("context")
    work_scopes = (
        ("life_material", "context.embedding.project"),
        ("subjective_memory", "context.embedding.project"),
    )

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if not item.reconciliation_required:
                continue
            if item.subject_id is None or item.deadline_at is None:
                raise ValueError("context work identity is incomplete")
            try:
                if item.idempotency_key is None:
                    raise ValueError
                source_version = int(item.idempotency_key.split(":", 2)[1])
            except IndexError, TypeError, ValueError:
                raise ValueError("context work source identity is invalid") from None
            successor_generation = item.generation + 1
            retry_seconds = {2: 60, 3: 300}.get(successor_generation)
            retry_at = (
                datetime.now(UTC) + timedelta(seconds=retry_seconds)
                if retry_seconds is not None
                else None
            )
            await transaction.execute(
                """INSERT INTO armi.context_embedding_failures (
                       context_embedding_failure_id,work_id,subject_id,
                       life_generation_id,source_kind,source_ref,source_version,
                       model_binding,work_generation,disposition,error_code,retry_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    uuid7(),
                    item.work_id,
                    item.subject_id,
                    scope.life_generation_id,
                    item.owner_kind,
                    item.owner_ref,
                    source_version,
                    EMBEDDING_BINDING_ID,
                    item.generation,
                    "retry_wait" if retry_at is not None else "degraded",
                    item.last_error_code or "WORK-ATTEMPTS-EXHAUSTED",
                    retry_at,
                ),
            )
            if retry_at is not None:
                await reconciliation.fail_with_successor(
                    item.work_id,
                    successor_work_id=uuid7(),
                    reason_code="REC-CONTEXT-EMBEDDING-RETRY",
                    not_before=retry_at,
                    deadline_at=retry_at + timedelta(hours=1),
                    max_attempts=3,
                )
            else:
                await transaction.execute(
                    """UPDATE armi.context_embedding_coverage
                       SET coverage_state='degraded',scanning_epoch=NULL,
                           source_kind=NULL,after_source_ref=NULL,
                           pending_work_count=greatest(pending_work_count-1,0),
                           updated_at=statement_timestamp()
                       WHERE model_binding=%s""",
                    (EMBEDDING_BINDING_ID,),
                )
                await reconciliation.fail(
                    item.work_id,
                    reason_code="REC-CONTEXT-EMBEDDING-DEGRADED",
                )
        return RecoveryContribution(
            self.owner_identity,
            metrics=(
                RecoveryMetricContribution(
                    "context.reconciliation_required_count",
                    sum(item.reconciliation_required for item in work),
                ),
            ),
        )


__all__ = ("ContextRecoveryParticipant",)
