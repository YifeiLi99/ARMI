"""Independent Mood commits, using a disposable database and a test appraiser."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid7

import psycopg
import pytest
from armi_data_rights.api import (
    DataRightsApplyRequest,
    DataRightsDiscoveryRequest,
    DataRightsRelatedRef,
)
from armi_kernel.application import PriceCatalog, WorkType
from armi_mood.api import Appraisal, EvaluatedAppraisal, MoodEvent, MoodViolation
from armi_runtime.application.mood_evaluation import RuntimeMoodEvaluation
from armi_runtime.composition.postgresql_test import (
    bootstrap_cognition_context,
    bootstrap_experience_owner,
    bootstrap_mood,
    bootstrap_mood_data_rights,
)

from tests.postgresql import test_postgresql_integration as support

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.test_group("mood", "cognition"),
    pytest.mark.skipif(
        not os.environ.get("S009_ADMIN_DSN"), reason="isolated PostgreSQL required"
    ),
]


@pytest.mark.parametrize(
    "outcome", ["success", "failure", "cancelled", "subject_conflict", "mood_conflict"]
)
def test_mood_is_independent_and_only_success_releases_context(outcome):
    case = support.PostgreSQLIntegrationTests()
    case.setUpClass()

    async def probe(fixture, born, ids, fence, old_lease):
        with psycopg.connect(fixture.provisioner_dsn) as db:
            db.execute(
                "UPDATE armi.cognitive_episodes SET status='preparing', final_disposition=NULL, validated_at=NULL,model_returned_at=NULL,prepared_at=NULL,compiled_context_digest=NULL,context_manifest_artifact_id=NULL,compiled_context_artifact_id=NULL,validation_status=NULL,candidate_validation_id=NULL,validated_model_attempt_id=NULL,change_set_artifact_id=NULL WHERE cognitive_episode_id=%s",
                (ids["episode"],),
            )
            db.execute(
                "UPDATE armi.durable_work SET work_kind='mood.evaluate',max_attempts=1 WHERE work_id=%s",
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
        mood = bootstrap_mood()
        episodes = bootstrap_cognition_context(
            experiences=bootstrap_experience_owner(),
            maintenance=support.PostgreSQLSubjectMaintenance(),
        )
        lease = replace(old_lease, work_kind=WorkType.MOOD_EVALUATE)
        event = MoodEvent(
            "test:event:1",
            born.subject_id,
            ids["episode"],
            ids["evidence"],
            1,
            datetime.now(UTC),
            "A confirmed benefit to an existing goal",
        )
        calls = []

        class Appraiser:
            async def evaluate(self, *, assessment, context):
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
                if outcome == "mood_conflict":
                    # A competing owner commit changes the head after dispatch.
                    async with factory.unit_of_work() as unit:
                        other = await mood.events.begin(
                            unit.transaction,
                            event=replace(event, event_key="other:1"),
                            context={"layers": []},
                        )
                        await mood.events.apply(
                            unit.transaction,
                            assessment=other,
                            result=evaluated(other),
                            at=datetime.now(UTC),
                        )
                return evaluated(assessment)

        def evaluated(assessment):
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
            return EvaluatedAppraisal(
                Appraisal.model_validate(fields),
                str(assessment.assessment_id),
                {},
                100,
                0,
            )

        service = RuntimeMoodEvaluation(
            factory=factory,
            episodes=episodes,
            store=mood.events,
            appraiser=Appraiser(),
            prices=PriceCatalog(()),
        )
        await factory.open()
        try:
            if outcome == "success":
                await service.evaluate(
                    event=event, lease=lease, compiled_context=b'{"layers":[]}'
                )
                # Main cognition rollback cannot undo the prior transaction.
                with pytest.raises(RuntimeError):
                    async with factory.unit_of_work() as unit:
                        await unit.transaction.execute(
                            "UPDATE armi.subjects SET subject_version=99"
                        )
                        raise RuntimeError("main model failed")
                async with factory.unit_of_work() as unit:
                    duplicate = await mood.events.begin(
                        unit.transaction, event=event, context={"layers": []}
                    )
                    assert duplicate.status == "applied"
                    snapshot = await mood.read.snapshot(
                        unit.transaction, subject_id=born.subject_id
                    )
                    assert snapshot.version == 2 and snapshot.current.valence > 0
            else:
                with pytest.raises(
                    asyncio.CancelledError if outcome == "cancelled" else MoodViolation
                ):
                    await service.evaluate(
                        event=event, lease=lease, compiled_context=b'{"layers":[]}'
                    )
            assert len(calls) == 1
            with psycopg.connect(fixture.runtime_dsn) as db:
                receipt = db.execute(
                    "SELECT status,context_document,mood_revision_id FROM armi.mood_assessments WHERE event_key='test:event:1'"
                ).fetchone()
                assert receipt is not None
                assert receipt[0] == (
                    "applied"
                    if outcome == "success"
                    else "interrupted"
                    if outcome == "cancelled"
                    else "failed"
                )
                assert receipt[1]["event"]["content"] == event.summary
                queued = db.execute(
                    "SELECT count(*) FROM armi.durable_work WHERE work_kind='cognition.context.prepare'"
                ).fetchone()
                assert queued == (int(outcome == "success"),)
                linked = db.execute(
                    "SELECT mood_assessment_id,base_subject_version FROM armi.cognitive_episodes WHERE cognitive_episode_id=%s",
                    (ids["episode"],),
                ).fetchone()
                assert linked is not None
                assert (linked[0] is not None) == (outcome == "success")
                assert linked[1] == int(outcome == "success")
            if outcome == "success":
                # A later appraisal can contain a copy of a source even before
                # main cognition freezes its own Context. Deletion must find it.
                rights = bootstrap_mood_data_rights()
                order_id, party_id = uuid7(), uuid7()
                async with factory.unit_of_work() as unit:
                    copied = await mood.events.begin(
                        unit.transaction,
                        event=replace(event, event_key="copy:1", source_ref=uuid7()),
                        context={
                            "layers": [
                                {
                                    "items": [
                                        {
                                            "source": {
                                                "reference": str(event.source_ref)
                                            },
                                            "content": "private copy",
                                        }
                                    ]
                                }
                            ]
                        },
                    )
                    discovery = await rights.discover(
                        unit.transaction,
                        DataRightsDiscoveryRequest(
                            order_id,
                            party_id,
                            (DataRightsRelatedRef("evidence", event.source_ref),),
                        ),
                    )
                    assert {item.ref for item in discovery.related_refs} == {
                        calls[0],
                        copied.assessment_id,
                    }
                    await rights.apply(
                        unit.transaction,
                        DataRightsApplyRequest(
                            order_id,
                            party_id,
                            "delete_related",
                            discovery.related_refs,
                            discovery.targets,
                            (),
                        ),
                    )
                    head = await mood.read.snapshot(
                        unit.transaction, subject_id=born.subject_id
                    )
                    assert head.state.episodes[0].summary == ""
                    assert head.current.valence > 0
                    rows = await (
                        await unit.transaction.execute(
                            "SELECT context_document,appraisal,answers FROM armi.mood_assessments"
                        )
                    ).fetchall()
                    assert all(row == (None, None, None) for row in rows)
                async with factory.unit_of_work() as unit:
                    neutral = await mood.events.begin(
                        unit.transaction,
                        event=replace(event, event_key="neutral:1", source_ref=uuid7()),
                        context={"layers": []},
                    )
                    positive = evaluated(neutral)
                    await mood.events.apply(
                        unit.transaction,
                        assessment=neutral,
                        result=replace(
                            positive,
                            appraisal=positive.appraisal.model_copy(update={"gain": 0}),
                        ),
                        at=datetime.now(UTC),
                    )
                    receipt = await (
                        await unit.transaction.execute(
                            "SELECT status FROM armi.mood_assessments WHERE mood_assessment_id=%s",
                            (neutral.assessment_id,),
                        )
                    ).fetchone()
                    assert receipt == ("unchanged",)
        finally:
            await factory.close()

    try:
        case._exercise_creator_reply(mood_probe=probe)
    finally:
        case.tearDownClass()
