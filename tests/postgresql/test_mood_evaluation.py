"""One event request, independent Mood/Mind commits and no implicit replay."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid7

import psycopg
import pytest
from armi_cognition.api import EventAppraisalResult
from armi_data_rights.api import (
    DataRightsApplyRequest,
    DataRightsDiscoveryRequest,
    DataRightsRelatedRef,
)
from armi_kernel.application import PriceCatalog, WorkType
from armi_mind.api import (
    Association,
    MindChoice,
    MindEvidence,
    MindVariable,
    Opportunity,
)
from armi_mood.api import Appraisal, EvaluatedAppraisal, MoodEvent, MoodViolation
from armi_runtime.application.mood_evaluation import RuntimeMoodEvaluation
from armi_runtime.composition.postgresql_test import (
    bootstrap_cognition_context,
    bootstrap_event_appraisals,
    bootstrap_experience_owner,
    bootstrap_mind,
    bootstrap_mind_data_rights,
    bootstrap_mood,
)

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.test_group("mind", "mood", "cognition"),
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "mood_invalid",
        "mind_invalid",
        "mood_rejected",
        "mind_rejected",
        "interrupted_after_mood",
        "failure",
        "cancelled",
        "subject_conflict",
    ],
)
def test_joint_event_commits_valid_parts_and_only_full_success_releases_context(
    outcome,
):
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()

    async def probe(fixture, born, ids, fence, old_lease):
        with psycopg.connect(fixture.provisioner_dsn) as db:
            initial_attempts = db.execute(
                "SELECT count(*) FROM armi.cognitive_attempts"
            ).fetchone()
            db.execute(
                "UPDATE armi.cognitive_episodes SET status='preparing',final_disposition=NULL,validated_at=NULL,"
                "model_returned_at=NULL,prepared_at=NULL,compiled_context_digest=NULL,context_manifest_artifact_id=NULL,"
                "compiled_context_artifact_id=NULL,validation_status=NULL,candidate_validation_id=NULL,"
                "validated_model_attempt_id=NULL,change_set_artifact_id=NULL WHERE cognitive_episode_id=%s",
                (ids["episode"],),
            )
            db.execute(
                "UPDATE armi.durable_work SET work_kind='event.appraise',max_attempts=1 WHERE work_id=%s",
                (ids["commit_work"],),
            )
        factory = support.PostgreSQLUnitOfWorkFactory(
            fixture.runtime_dsn,
            environment_id=fixture.environment_id,
            pool_min=1,
            pool_max=2,
            acquire_timeout_seconds=2,
            statement_timeout_seconds=5,
            authority_admission=lambda: fence,
        )
        mood, mind = bootstrap_mood(), bootstrap_mind()
        store = bootstrap_event_appraisals(mood=mood.read, mind=mind.read)
        episodes = bootstrap_cognition_context(
            experiences=bootstrap_experience_owner(),
            maintenance=support.PostgreSQLSubjectMaintenance(),
        )
        event = MoodEvent(
            "test:event:1",
            born.subject_id,
            ids["episode"],
            ids["evidence"],
            1,
            datetime.now(UTC),
            "A confirmed benefit and an unresolved valuable question",
        )
        calls = []

        class Appraiser:
            async def evaluate_event(self, *, assessment, context, targets):
                calls.append(assessment.assessment_id)
                if outcome == "failure":
                    raise MoodViolation("MOOD-JEV-HTTP-FAILED")
                if outcome == "cancelled":
                    raise asyncio.CancelledError()
                if outcome == "subject_conflict":
                    with psycopg.connect(fixture.provisioner_dsn) as db:
                        db.execute(
                            "UPDATE armi.subjects SET subject_version=subject_version+1"
                        )
                fields: dict[str, object] = {
                    name: None
                    for name, field in Appraisal.model_fields.items()
                    if field.is_required()
                }
                fields.update(
                    agency="circumstance",
                    intent="not_applicable",
                    phase="realized",
                    epistemic="confirmed",
                    self_scope="none",
                    outcome_change="unchanged",
                    relevance=1,
                    gain=1,
                    loss=0,
                )
                evaluated = EvaluatedAppraisal(
                    Appraisal.model_validate(fields),
                    str(assessment.assessment_id),
                    {},
                    100,
                    0,
                )
                evidence = tuple(
                    MindEvidence(
                        t.object,
                        event.event_key,
                        t.basis_refs,
                        event.occurred_at,
                        (
                            (MindVariable.CONTACT_GAP, MindChoice.FULL),
                            (MindVariable.IMPORTANCE, MindChoice.FULL),
                        ),
                        Association.ACTIVE,
                        Opportunity.AVAILABLE,
                    )
                    for t in targets
                )
                return EventAppraisalResult(
                    None if outcome == "mood_invalid" else evaluated,
                    None if outcome == "mind_invalid" else evidence,
                    "MOOD-INVALID" if outcome == "mood_invalid" else None,
                    "MIND-INVALID" if outcome == "mind_invalid" else None,
                    100,
                    0,
                )

        class MoodOwner:
            async def apply(self, *args, **kwargs):
                if outcome == "mood_rejected":
                    raise ValueError("owner validation rejected")
                return await mood.events.apply(*args, **kwargs)

        class MindOwner:
            async def apply_event(self, *args, **kwargs):
                if outcome == "mind_rejected":
                    raise ValueError("owner validation rejected")
                if outcome == "interrupted_after_mood":
                    raise asyncio.CancelledError()
                return await mind.event.apply_event(*args, **kwargs)

        service = RuntimeMoodEvaluation(
            factory=factory,
            episodes=episodes,
            store=store,
            mood=MoodOwner(),
            mind=MindOwner(),
            appraiser=Appraiser(),
            prices=PriceCatalog(()),
        )
        lease = replace(old_lease, work_kind=WorkType.EVENT_APPRAISE)
        await factory.open()
        try:
            if outcome == "success":
                await service.evaluate(
                    event=event, lease=lease, compiled_context=b'{"layers":[]}'
                )
                with pytest.raises(RuntimeError):
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            "UPDATE armi.subjects SET subject_version=99"
                        )
                        raise RuntimeError("later main model transaction failed")
            else:
                with pytest.raises(
                    asyncio.CancelledError
                    if outcome in {"cancelled", "interrupted_after_mood"}
                    else MoodViolation
                ):
                    await service.evaluate(
                        event=event, lease=lease, compiled_context=b'{"layers":[]}'
                    )
            async with factory.unit_of_work() as unit:
                duplicate = await store.begin(
                    unit.transaction, event=event, context={"layers": []}
                )
                assert duplicate.status != "new"
                mood_head = await mood.read.snapshot(
                    unit.transaction, subject_id=born.subject_id
                )
                mind_head = await mind.read.current_head(
                    unit.transaction, subject_id=born.subject_id
                )
                assert mood_head.version == (
                    2
                    if outcome
                    in {
                        "success",
                        "mind_invalid",
                        "mind_rejected",
                        "interrupted_after_mood",
                    }
                    else 1
                )
                assert mind_head.version == (
                    2 if outcome in {"success", "mood_invalid", "mood_rejected"} else 1
                )
            assert len(calls) == 1
            with psycopg.connect(fixture.provisioner_dsn) as db:
                receipt = db.execute(
                    "SELECT status,mood_status,mind_status,input_tokens FROM armi.event_appraisals"
                ).fetchone()
                assert receipt is not None
                assert receipt[0] == (
                    "applied"
                    if outcome == "success"
                    else "interrupted"
                    if outcome in {"cancelled", "interrupted_after_mood"}
                    else "failed"
                )
                if outcome in {"success", "mind_invalid", "mood_invalid"}:
                    assert receipt[3] == 100
                assert db.execute(
                    "SELECT count(*) FROM armi.durable_work WHERE work_kind='cognition.context.prepare'"
                ).fetchone() == (int(outcome == "success"),)
                assert (
                    db.execute(
                        "SELECT count(*) FROM armi.cognitive_attempts"
                    ).fetchone()
                    == initial_attempts
                )
            if outcome == "success":
                participant = bootstrap_mind_data_rights()
                party = uuid7()
                refs = (DataRightsRelatedRef("external-evidence", event.source_ref),)
                async with factory.unit_of_work() as unit:
                    discovered = await participant.discover(
                        unit.transaction,
                        DataRightsDiscoveryRequest(uuid7(), party, refs),
                    )
                    assert discovered.targets
                    assert await mind.read.consideration_signals(
                        unit.transaction, subject_id=born.subject_id
                    )
                    await participant.apply(
                        unit.transaction,
                        DataRightsApplyRequest(
                            uuid7(),
                            party,
                            "delete_related",
                            (*refs, *discovered.related_refs),
                            tuple(
                                replace(t, responsible_owner="mind")
                                for t in discovered.targets
                            ),
                            (),
                        ),
                    )
                async with factory.unit_of_work() as unit:
                    assert not await mind.read.consideration_signals(
                        unit.transaction, subject_id=born.subject_id
                    )
                    head = await mind.read.current_head(
                        unit.transaction, subject_id=born.subject_id
                    )
                    assert json.loads(head.canonical_state)["objects"] == []
                    assert await mind.read.history_is_continuous(
                        unit.transaction, subject_id=born.subject_id
                    )
        finally:
            await factory.close()

    try:
        case._exercise_creator_reply(mood_probe=probe)
    finally:
        case.tearDownClass()
