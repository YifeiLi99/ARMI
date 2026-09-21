"""Real attempt persistence and interruption between format regenerations."""

from __future__ import annotations

import asyncio
import os
import selectors
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from armi_cognition._model_contract import load_active_binding
from armi_cognition._model_postgresql import PostgreSQLCognitiveModelRepository
from armi_kernel.application import (
    ArtifactId,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
    WorkOwner,
    WorkType,
)
from armi_runtime.composition.postgresql_test import bootstrap_context_candidate_read

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


@pytest.mark.parametrize("outcome", ["returned", "exhausted", "interrupted"])
def test_format_retry_attempts_preserve_evidence_and_do_not_resume(
    monkeypatch, outcome
):
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()
    captured: dict[str, Any] = {}

    def capture(fixture, fence, ids, payloads, stage, **_kwargs):
        captured.update(fixture=fixture, fence=fence, ids=ids)

    monkeypatch.setattr(case, "_verify_reply_interruption", capture)
    try:
        # Reuse the integration fixture before any Subject Commit/effect executes.
        case._exercise_creator_reply(interruption_stage="finalizing")
        fixture, fence, ids = (captured[key] for key in ("fixture", "fence", "ids"))
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "UPDATE armi.cognitive_episodes SET status='calling_model', model_returned_at=NULL WHERE cognitive_episode_id=%s",
                (ids["episode"],),
            )
            artifact_ids = connection.execute(
                "SELECT request_artifact_id,response_artifact_id FROM armi.cognitive_attempts WHERE model_attempt_id=%s",
                (ids["model_attempt"],),
            ).fetchone()
            assert artifact_ids is not None
            request_id, response_id = artifact_ids

        async def exercise():
            factory = support.PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: fence,
            )
            catalog = support.ArtifactCatalogRepository()
            repository = PostgreSQLCognitiveModelRepository(
                bootstrap_context_candidate_read().cognition,
                catalog,
                support.bootstrap_opportunity_cognition(),
            )
            binding = replace(
                load_active_binding(Path("configs/model-bindings.yaml")),
                response_contract_version="armi.creator-cognitive-act-candidate.v7",
            )
            await factory.open()
            try:
                async with factory.unit_of_work() as unit:
                    work = await unit.work.latest(
                        owner=WorkOwner("cognitive_episode", ids["episode"]),
                        work_kind=WorkType.COGNITION_EXECUTE,
                    )
                    assert work is not None and work.lease is not None
                    snapshot = await repository.snapshot(unit, work)
                    request = await catalog.retained_ref(unit, ArtifactId(request_id))
                    response = await catalog.retained_ref(unit, ArtifactId(response_id))
                    assert request is not None and response is not None
                attempt = None
                for number in range(2, 3 if outcome == "interrupted" else 6):
                    async with factory.unit_of_work() as unit:
                        attempt = await repository.prepare_attempt(
                            unit,
                            lease=work.lease,
                            snapshot=snapshot,
                            binding=binding,
                            request_artifact=request,
                        )
                        assert attempt is not None
                        await repository.mark_dispatched(
                            unit,
                            lease=work.lease,
                            attempt_id=attempt,
                            episode_id=snapshot.episode_id,
                        )
                    result = ModelInvocationResult(
                        ModelResultStatus.SUCCEEDED,
                        f"attempt-{number}",
                        binding.model_id,
                        b"controlled-response",
                        ModelUsage(20, 10, 0),
                        response_error_code=(
                            None
                            if outcome == "returned" and number == 5
                            else "MODEL-RESPONSE-SCHEMA"
                        ),
                    )
                    async with factory.unit_of_work() as unit:
                        await repository.settle_success(
                            unit,
                            lease=work.lease,
                            snapshot=snapshot,
                            attempt_id=attempt,
                            response_artifact=response,
                            result=result,
                        )
                async with factory.unit_of_work() as unit:
                    assert attempt is not None
                    if outcome == "interrupted":
                        assert await repository.end_abandoned_finalization(unit, work)
                    else:
                        await repository.finalize_primary_success(
                            unit,
                            lease=work.lease,
                            snapshot=snapshot,
                            attempt_id=attempt,
                            response_artifact=response,
                        )
                        if outcome == "exhausted":
                            await repository.fail_episode(
                                unit,
                                lease=work.lease,
                                snapshot=snapshot,
                                code="MODEL-RESPONSE-SCHEMA",
                            )
            finally:
                await factory.close()

        asyncio.run(
            exercise(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            rows = connection.execute(
                "SELECT attempt_no,request_artifact_id,response_artifact_id,error_code FROM armi.cognitive_attempts ORDER BY attempt_no"
            ).fetchall()
            assert len(rows) == (2 if outcome == "interrupted" else 5)
            assert [row[0] for row in rows] == list(range(1, len(rows) + 1))
            assert all(row[1:3] == (request_id, response_id) for row in rows)
            assert all(row[3] is None for row in rows)
            assert connection.execute(
                "SELECT count(*) FROM armi.audit_events WHERE operation='cognition.model.response.format_rejected'"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT status FROM armi.cognitive_episodes"
            ).fetchone() == (
                {
                    "returned": "finalizing",
                    "exhausted": "failed",
                    "interrupted": "cancelled",
                }[outcome],
            )
            assert connection.execute(
                "SELECT count(*) FROM armi.subject_commits"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM armi.effects"
            ).fetchone() == (0,)
    finally:
        case.tearDownClass()
