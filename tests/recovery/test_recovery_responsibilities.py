from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid7

from armi_kernel.application import RecoveryDecision, RuntimeFence
from armi_runtime.adapters.persistence.audit_events import PostgreSQLAuditWriter
from armi_runtime.adapters.persistence.recovery_responsibilities import (
    repair_terminal_cognitive_responsibilities,
    repair_work,
)


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(self, *, episode_id: object, work_id: object) -> None:
        self._episode_id = episode_id
        self._work_id = work_id

    async def execute(
        self,
        statement: str,
        _parameters: tuple[object, ...] | None = None,
    ) -> _Cursor:
        if "WHERE work.status = 'leased'" in statement:
            return _Cursor([])
        if "UPDATE armi.cognitive_episodes AS episode" in statement:
            return _Cursor([(self._episode_id, self._work_id)])
        raise AssertionError(statement)


class _Writer:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def append(self, event: tuple[str, object]) -> None:
        self.events.append(event)


def test_failed_work_terminally_reconciles_owning_cognitive_episode() -> None:
    episode_id = uuid7()
    work_id = uuid7()
    connection = _Connection(episode_id=episode_id, work_id=work_id)
    writer = _Writer()

    findings, requeued, terminal = asyncio.run(
        repair_work(
            cast(Any, connection),
            cast(PostgreSQLAuditWriter, writer),
            cast(RuntimeFence, object()),
            lambda _fence, operation, target: (operation, target),  # type: ignore[arg-type,return-value]
        )
    )

    assert requeued == 0
    assert terminal == 0
    assert len(findings) == 1
    assert findings[0].kind == "cognitive_episode"
    assert findings[0].decision is RecoveryDecision.TERMINAL
    assert findings[0].reason_code == "REC-EPISODE-WORK-FAILED"
    assert findings[0].reference == episode_id
    assert writer.events == [("cognition.episode.recovered.failed", episode_id)]


class _CandidateRejectionConnection:
    def __init__(
        self,
        *,
        rejected_opportunity_id: object,
        failed_opportunity_id: object,
        operation_id: object,
    ) -> None:
        self._rejected_opportunity_id = rejected_opportunity_id
        self._failed_opportunity_id = failed_opportunity_id
        self._operation_id = operation_id

    async def execute(
        self,
        statement: str,
        _parameters: tuple[object, ...] | None = None,
    ) -> _Cursor:
        if "UPDATE armi.opportunities AS opportunity" in statement:
            return _Cursor(
                [
                    (self._rejected_opportunity_id, "candidate_rejected"),
                    (self._failed_opportunity_id, "failed"),
                ]
            )
        if "UPDATE armi.action_operations AS operation" in statement:
            return _Cursor([(self._operation_id,)])
        raise AssertionError(statement)


def test_candidate_rejection_recovery_closes_opportunity_and_codex_operation() -> None:
    rejected_opportunity_id = uuid7()
    failed_opportunity_id = uuid7()
    operation_id = uuid7()
    connection = _CandidateRejectionConnection(
        rejected_opportunity_id=rejected_opportunity_id,
        failed_opportunity_id=failed_opportunity_id,
        operation_id=operation_id,
    )
    writer = _Writer()

    findings = asyncio.run(
        repair_terminal_cognitive_responsibilities(
            cast(Any, connection),
            cast(PostgreSQLAuditWriter, writer),
            cast(RuntimeFence, object()),
            lambda _fence, operation, target: (operation, target),  # type: ignore[arg-type,return-value]
        )
    )

    assert [(item.kind, item.reason_code, item.reference) for item in findings] == [
        (
            "opportunity",
            "REC-OPPORTUNITY-EPISODE-CANDIDATE-REJECTED",
            rejected_opportunity_id,
        ),
        (
            "opportunity",
            "REC-OPPORTUNITY-EPISODE-FAILED",
            failed_opportunity_id,
        ),
        (
            "creator_response_operation",
            "REC-CODEX-RESULT-CANDIDATE-REJECTED",
            operation_id,
        ),
    ]
    assert writer.events == [
        ("opportunity.recovered.candidate_rejected", rejected_opportunity_id),
        ("opportunity.recovered.failed", failed_opportunity_id),
        ("codex.result.recovered.candidate_rejected", operation_id),
    ]
