"""Runtime-owned subject fencing and cancellation of cognition work."""

from uuid import UUID

from .recovery import (
    OwnerReconciliationContext,
    RecoveryOwnerIdentity,
    RecoveryWorkSnapshot,
)
from .transactions import PostgreSQLTransaction


async def subject_context_current(
    transaction: PostgreSQLTransaction,
    *,
    subject_id: UUID,
    subject_version: int,
    state_epoch: int,
    bundle_activation_id: UUID,
) -> bool:
    row = await (
        await transaction.execute(
            """SELECT subject_version,state_epoch,current_bundle_activation_id
           FROM armi.subjects WHERE subject_id=%s AND status='active' FOR UPDATE""",
            (subject_id,),
        )
    ).fetchone()
    return row is not None and tuple(row) == (
        subject_version,
        state_epoch,
        bundle_activation_id,
    )


async def cancel_cognition_work(
    transaction: PostgreSQLTransaction, *, episode_ids: tuple[UUID, ...]
) -> None:
    rows = await (
        await transaction.execute(
            """SELECT work_id,work_kind,owner_kind,owner_ref,status,attempt_count,max_attempts
           FROM armi.durable_work WHERE owner_kind='cognitive_episode'
             AND owner_ref=ANY(%s::uuid[]) AND status IN ('ready','leased') FOR UPDATE""",
            (list(episode_ids),),
        )
    ).fetchall()
    work = tuple(RecoveryWorkSnapshot(*row) for row in rows)
    for item in work:
        custody = OwnerReconciliationContext(
            transaction,
            RecoveryOwnerIdentity("cognition"),
            (item,),
        )
        await custody.cancel(item.work_id, reason_code="REC-HUMAN-INPUT-PREEMPTED")
