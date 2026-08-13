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
    failed_episodes = await (
        await connection.execute(
            """
            UPDATE armi.cognitive_episodes AS episode
            SET status = 'failed',
                failure_code = work.last_error_code
            FROM armi.durable_work AS work
            WHERE work.owner_kind = 'cognitive_episode'
              AND work.owner_ref = episode.cognitive_episode_id
              AND work.status = 'failed'
              AND work.last_error_code IS NOT NULL
              AND episode.status NOT IN (
                  'completed', 'stale', 'failed', 'cancelled'
              )
            RETURNING episode.cognitive_episode_id, work.work_id
            """
        )
    ).fetchall()
    for episode_id, _work_id in failed_episodes:
        findings.append(
            RecoveryFinding(
                "cognitive_episode",
                RecoveryDecision.TERMINAL,
                "REC-EPISODE-WORK-FAILED",
                episode_id,
            )
        )
        await writer.append(
            audit_factory(fence, "cognition.episode.recovered.failed", episode_id)
        )
    return tuple(findings), requeued, terminal


async def repair_terminal_cognitive_responsibilities(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    writer: PostgreSQLAuditWriter,
    fence: RuntimeFence,
    audit_factory: AuditFactory,
) -> tuple[RecoveryFinding, ...]:
    """Close opportunities and operations left open by terminal cognition."""

    findings: list[RecoveryFinding] = []
    opportunities = await (
        await connection.execute(
            """
            UPDATE armi.opportunities AS opportunity
            SET current_disposition = CASE
                    WHEN episode.status = 'cancelled' THEN 'cancelled'
                    ELSE 'resolved'
                END,
                resolved_at = statement_timestamp()
            FROM armi.cognitive_episodes AS episode
            WHERE episode.opportunity_id = opportunity.opportunity_id
              AND episode.status IN ('candidate_rejected', 'failed', 'cancelled')
              AND opportunity.current_disposition = 'selected'
            RETURNING opportunity.opportunity_id, episode.status
            """
        )
    ).fetchall()
    for opportunity_id, episode_status in opportunities:
        status = str(episode_status)
        suffix = status.replace("_", "-").upper()
        findings.append(
            RecoveryFinding(
                "opportunity",
                RecoveryDecision.TERMINAL,
                f"REC-OPPORTUNITY-EPISODE-{suffix}",
                opportunity_id,
            )
        )
        await writer.append(
            audit_factory(
                fence,
                f"opportunity.recovered.{status}",
                opportunity_id,
            )
        )
    return tuple(findings)


__all__ = ()
