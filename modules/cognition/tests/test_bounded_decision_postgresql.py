"""Finite Jev decisions persist through the real model attempt owner."""

from __future__ import annotations

import asyncio
import os
import selectors
from dataclasses import replace
from typing import Any, cast

import psycopg
import pytest
from armi_cognition._model_postgresql import PostgreSQLCognitiveModelRepository
from armi_kernel.application import WorkOwner, WorkType
from armi_runtime.composition.postgresql_test import (
    JevAutonomyCheck,
    bootstrap_context_candidate_read,
)

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.test_group("cognition", "schema"),
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


def test_bounded_decision_attempt_preserves_binding_and_rejects_unknown_profile(
    monkeypatch,
):
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()
    captured: dict[str, Any] = {}

    def capture(fixture, fence, ids, _payloads, _stage, **_kwargs):
        captured.update(fixture=fixture, fence=fence, ids=ids)

    monkeypatch.setattr(case, "_verify_reply_interruption", capture)
    try:
        # Keep a real frozen Context and leased cognition work before Subject Commit.
        case._exercise_creator_reply(interruption_stage="finalizing")
        fixture, fence, ids = (captured[key] for key in ("fixture", "fence", "ids"))
        with psycopg.connect(fixture.provisioner_dsn) as connection:
            connection.execute(
                "UPDATE armi.cognitive_episodes SET status='calling_model',"
                "model_returned_at=NULL WHERE cognitive_episode_id=%s",
                (ids["episode"],),
            )

        async def prepare():
            factory = support.PostgreSQLUnitOfWorkFactory(
                fixture.runtime_dsn,
                environment_id=fixture.environment_id,
                pool_min=1,
                pool_max=1,
                acquire_timeout_seconds=2,
                statement_timeout_seconds=5,
                authority_admission=lambda: fence,
            )
            repository = PostgreSQLCognitiveModelRepository(
                bootstrap_context_candidate_read().cognition,
                support.ArtifactCatalogRepository(),
                support.bootstrap_opportunity_cognition(),
            )
            decision = JevAutonomyCheck(
                credentials=cast(Any, None),
                locator=None,
                timeout_seconds=5,
                decision_check=True,
            )
            # Bounded judgment keeps the candidate contract of the frozen purpose.
            binding = replace(
                decision.binding,
                response_contract_kind="armi.creator-cognitive-act-candidate",
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
                with pytest.raises(support.DatabaseTransactionError) as unknown:
                    async with factory.unit_of_work() as unit:
                        await repository.prepare_attempt(
                            unit,
                            lease=work.lease,
                            snapshot=snapshot,
                            binding=replace(binding, profile="unknown_profile"),
                            request_artifact=None,
                        )
                assert unknown.value.code == "DB-TX-CHECK"
                cause = unknown.value.__context__
                assert isinstance(cause, psycopg.errors.CheckViolation)
                assert cause.diag.constraint_name == (
                    "cognitive_attempts_profile_check"
                )
                async with factory.unit_of_work() as unit:
                    attempt = await repository.prepare_attempt(
                        unit,
                        lease=work.lease,
                        snapshot=snapshot,
                        binding=binding,
                        request_artifact=None,
                    )
                    assert attempt is not None
                return attempt, binding
            finally:
                await factory.close()

        attempt, binding = asyncio.run(
            prepare(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
        with psycopg.connect(fixture.runtime_dsn) as connection:
            row = connection.execute(
                "SELECT profile,provider,model_id,credential_identity,"
                "candidate_contract_kind,dispatch_status,request_artifact_id "
                "FROM armi.cognitive_attempts WHERE model_attempt_id=%s",
                (attempt.value,),
            ).fetchone()
            assert row == (
                "bounded_decision",
                "typesafe",
                binding.model_id,
                "mood.jev_api_key",
                "armi.creator-cognitive-act-candidate",
                "prepared",
                None,
            )
            assert connection.execute(
                "SELECT count(*) FROM armi.cognitive_attempts WHERE profile='unknown_profile'"
            ).fetchone() == (0,)
    finally:
        case.tearDownClass()
