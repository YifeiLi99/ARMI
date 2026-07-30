"""Package-private work and outbox repair mechanics for startup recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
from armi_kernel.application import (
    AuditDraft,
    RecoveryDecision,
    RecoveryFinding,
    RuntimeFence,
)

from .audit_events import PostgreSQLAuditWriter

AuditFactory = Callable[[RuntimeFence, str, UUID], AuditDraft]


async def repair_work(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    writer: PostgreSQLAuditWriter,
    fence: RuntimeFence,
    audit_factory: AuditFactory,
) -> tuple[tuple[RecoveryFinding, ...], int, int]:
    rows = await (
        await connection.execute(
            """
            SELECT
                work.work_id,
                work.lease_owner,
                work.deadline_at <= statement_timestamp()
                    OR work.attempt_count >= work.max_attempts,
                owner.status
            FROM armi.durable_work AS work
            LEFT JOIN armi.runtime_instances AS owner
              ON owner.runtime_instance_id = work.lease_owner
            WHERE work.status = 'leased'
            ORDER BY work.work_id
            FOR UPDATE OF work
            """
        )
    ).fetchall()
    findings: list[RecoveryFinding] = []
    requeued = terminal = 0
    for work_id, _owner_id, exhausted, owner_status in rows:
        if owner_status not in ("fenced", "stopped"):
            findings.append(
                RecoveryFinding(
                    "durable_work",
                    RecoveryDecision.BLOCKED,
                    "REC-WORK-OWNER-UNKNOWN",
                    work_id,
                )
            )
            continue
        if bool(exhausted):
            await connection.execute(
                """
                UPDATE armi.durable_work
                SET status = 'failed',
                    current_attempt_id = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = 'WORK-RECOVERY-EXHAUSTED',
                    updated_at = statement_timestamp()
                WHERE work_id = %s AND status = 'leased'
                """,
                (work_id,),
            )
            decision = RecoveryDecision.TERMINAL
            reason = "REC-WORK-TERMINAL"
            terminal += 1
        else:
            await connection.execute(
                """
                UPDATE armi.durable_work
                SET status = 'ready',
                    current_attempt_id = NULL,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = statement_timestamp()
                WHERE work_id = %s AND status = 'leased'
                """,
                (work_id,),
            )
            decision = RecoveryDecision.REQUEUED
            reason = "REC-WORK-REQUEUED"
            requeued += 1
        findings.append(RecoveryFinding("durable_work", decision, reason, work_id))
        await writer.append(
            audit_factory(fence, f"work.recovered.{decision.value}", work_id)
        )
    return tuple(findings), requeued, terminal


async def repair_outbox(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    writer: PostgreSQLAuditWriter,
    fence: RuntimeFence,
    audit_factory: AuditFactory,
) -> tuple[tuple[RecoveryFinding, ...], int, int]:
    rows = await (
        await connection.execute(
            """
            SELECT
                item.outbox_item_id,
                item.claimed_by,
                item.attempt_count >= item.max_attempts,
                owner.status
            FROM armi.outbox_items AS item
            LEFT JOIN armi.runtime_instances AS owner
              ON owner.runtime_instance_id = item.claimed_by
            WHERE item.status = 'claimed'
            ORDER BY item.outbox_item_id
            FOR UPDATE OF item
            """
        )
    ).fetchall()
    findings: list[RecoveryFinding] = []
    requeued = dead = 0
    for item_id, _owner_id, exhausted, owner_status in rows:
        if owner_status not in ("fenced", "stopped"):
            findings.append(
                RecoveryFinding(
                    "outbox",
                    RecoveryDecision.BLOCKED,
                    "REC-OUTBOX-OWNER-UNKNOWN",
                    item_id,
                )
            )
            continue
        if bool(exhausted):
            await connection.execute(
                """
                UPDATE armi.outbox_items
                SET status = 'dead',
                    claimed_by = NULL,
                    claim_expires_at = NULL,
                    last_error_code = 'OUTBOX-RECOVERY-EXHAUSTED',
                    updated_at = statement_timestamp()
                WHERE outbox_item_id = %s AND status = 'claimed'
                """,
                (item_id,),
            )
            decision = RecoveryDecision.TERMINAL
            reason = "REC-OUTBOX-DEAD"
            dead += 1
        else:
            await connection.execute(
                """
                UPDATE armi.outbox_items
                SET status = 'ready',
                    claimed_by = NULL,
                    claim_expires_at = NULL,
                    updated_at = statement_timestamp()
                WHERE outbox_item_id = %s AND status = 'claimed'
                """,
                (item_id,),
            )
            decision = RecoveryDecision.REQUEUED
            reason = "REC-OUTBOX-REQUEUED"
            requeued += 1
        findings.append(RecoveryFinding("outbox", decision, reason, item_id))
        await writer.append(
            audit_factory(fence, f"outbox.recovered.{decision.value}", item_id)
        )
    return tuple(findings), requeued, dead


__all__ = ()
