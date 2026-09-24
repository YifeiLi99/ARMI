"""Commit event appraisal before freezing the main cognition Context."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid7

from armi_cognition.api import (
    CognitionContextLifecyclePort,
    EventAppraisalStorePort,
    EventAppraiserPort,
)
from armi_kernel.application import (
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
    WorkType,
    diagnostic_scope,
    provider_meter_scope,
    record_diagnostic,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId
from armi_mind.api import MindEventPort, MindViolation
from armi_mood.api import (
    MoodEvent,
    MoodEventStorePort,
    MoodViolation,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory


class RuntimeMoodEvaluation:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        episodes: CognitionContextLifecyclePort,
        store: EventAppraisalStorePort,
        mood: MoodEventStorePort,
        mind: MindEventPort,
        appraiser: EventAppraiserPort,
        prices: PriceCatalog,
    ) -> None:
        self._factory = factory
        self._episodes = episodes
        self._store = store
        self._mood = mood
        self._mind = mind
        self._appraiser = appraiser
        self._prices = prices

    async def evaluate(
        self, *, event: MoodEvent, lease: WorkLease, compiled_context: bytes
    ) -> None:
        with diagnostic_scope(
            episode_id=event.episode_id,
            work_id=lease.work_id.value,
            attempt_id=lease.attempt_id.value,
        ):
            await self._evaluate(
                event=event, lease=lease, compiled_context=compiled_context
            )

    async def _evaluate(
        self, *, event: MoodEvent, lease: WorkLease, compiled_context: bytes
    ) -> None:
        record_diagnostic("appraisal.started", component="appraisal")
        async with self._factory.unit_of_work() as unit:
            await unit.work.validate_lease(lease)
            episode = await self._episodes.context_episode(
                unit.transaction, episode_id=event.episode_id
            )
            assessment = await self._store.begin(
                unit.transaction, event=event, context=json.loads(compiled_context)
            )
        if assessment.status not in {"new", "applied", "unchanged"}:
            raise MoodViolation("MOOD-EVENT-ALREADY-FAILED-OR-INTERRUPTED")

        async def save_usage(receipt: ProviderCallReceipt) -> None:
            async with self._factory.provider_usage_unit_of_work(
                receipt=receipt
            ) as unit:
                await self._store.record_provider_call(
                    unit.transaction,
                    assessment_id=assessment.assessment_id,
                    receipt=receipt,
                )

        async def capture(kind: Literal["request", "response"], content: str) -> None:
            async with self._factory.unit_of_work() as unit:
                await unit.work.validate_lease(lease)
                await self._store.record_transport(
                    unit.transaction,
                    assessment_id=assessment.assessment_id,
                    kind=kind,
                    content=content,
                )

        try:
            version = episode.base_subject_version
            if assessment.status == "new":
                with provider_meter_scope(
                    ProviderMeterScope(save_usage, self._prices, "event.appraise")
                ):
                    result = await self._appraiser.evaluate_event(
                        assessment=assessment.mood,
                        context=json.loads(compiled_context),
                        targets=assessment.targets,
                        capture=capture,
                    )
                record_diagnostic(
                    "appraisal.returned",
                    component="appraisal",
                    assessment_id=assessment.assessment_id,
                )
                # Each owner commits independently. A malformed sibling cannot
                # roll back a valid psychological result.
                for owner in ("mood", "mind"):
                    try:
                        async with self._factory.unit_of_work() as unit:
                            await unit.work.validate_lease(lease)
                            subject = await (
                                await unit.transaction.execute(
                                    "SELECT subject_version,state_epoch,current_bundle_activation_id "
                                    "FROM armi.subjects WHERE subject_id=%s AND status='active' FOR UPDATE",
                                    (event.subject_id,),
                                )
                            ).fetchone()
                            if subject is None or tuple(subject) != (
                                version,
                                episode.base_state_epoch,
                                episode.bundle_activation_id,
                            ):
                                raise MoodViolation("MOOD-EVENT-SUBJECT-STALE")
                            changed = False
                            revision_id = None
                            if owner == "mood":
                                if result.mood is not None:
                                    (
                                        changed,
                                        revision_id,
                                        emotional,
                                    ) = await self._mood.apply(
                                        unit.transaction,
                                        assessment=assessment.mood,
                                        result=result.mood,
                                        at=datetime.now(UTC),
                                    )
                                    await self._store.record_result(
                                        unit.transaction,
                                        assessment_id=assessment.assessment_id,
                                        owner="mood",
                                        status="applied" if emotional else "unchanged",
                                        revision_id=revision_id,
                                        payload={
                                            "appraisal": result.mood.appraisal.model_dump(
                                                mode="json"
                                            ),
                                            "answers": result.mood.answers,
                                        },
                                        error=None,
                                    )
                                else:
                                    await self._store.record_result(
                                        unit.transaction,
                                        assessment_id=assessment.assessment_id,
                                        owner="mood",
                                        status="failed",
                                        revision_id=None,
                                        payload=None,
                                        error=result.mood_failure,
                                    )
                            else:
                                if result.mind is not None:
                                    changed, revision_id = await self._mind.apply_event(
                                        unit.transaction,
                                        subject_id=event.subject_id,
                                        assessment_id=assessment.assessment_id,
                                        expected_version=assessment.mind.version,
                                        evidence=result.mind,
                                    )
                                    await self._store.record_result(
                                        unit.transaction,
                                        assessment_id=assessment.assessment_id,
                                        owner="mind",
                                        status="applied" if changed else "unchanged",
                                        revision_id=revision_id,
                                        payload={"objects": len(result.mind)},
                                        error=None,
                                    )
                                else:
                                    await self._store.record_result(
                                        unit.transaction,
                                        assessment_id=assessment.assessment_id,
                                        owner="mind",
                                        status="failed",
                                        revision_id=None,
                                        payload=None,
                                        error=result.mind_failure,
                                    )
                            if changed:
                                await unit.transaction.execute(
                                    "UPDATE armi.subjects SET subject_version=%s WHERE subject_id=%s",
                                    (version + 1, event.subject_id),
                                )
                        if changed:
                            version += 1
                        failure = (
                            result.mood_failure
                            if owner == "mood"
                            else result.mind_failure
                        )
                        record_diagnostic(
                            "appraisal.owner.committed",
                            component="appraisal",
                            level=logging.ERROR if failure else logging.INFO,
                            owner=owner,
                            assessment_id=assessment.assessment_id,
                            revision_id=revision_id,
                            subject_version=version,
                            outcome="failed"
                            if failure
                            else "applied"
                            if changed
                            else "unchanged",
                            result_code=failure,
                        )
                    except (ValueError, MindViolation, MoodViolation) as error:
                        record_diagnostic(
                            "appraisal.owner.failed",
                            component="appraisal",
                            level=logging.ERROR,
                            error=error,
                            owner=owner,
                            assessment_id=assessment.assessment_id,
                        )
                        if getattr(error, "code", "") == "MOOD-EVENT-SUBJECT-STALE":
                            raise
                        # A domain rejection rolls back only that owner's short
                        # transaction; a valid sibling can still be committed.
                        async with self._factory.unit_of_work() as unit:
                            await unit.work.validate_lease(lease)
                            await self._store.record_result(
                                unit.transaction,
                                assessment_id=assessment.assessment_id,
                                owner=owner,
                                status="failed",
                                revision_id=None,
                                payload=None,
                                error=f"{owner.upper()}-EVENT-REJECTED",
                            )
                async with self._factory.unit_of_work() as unit:
                    ready = await self._store.finish(
                        unit.transaction,
                        assessment_id=assessment.assessment_id,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )
                if not ready:
                    raise MoodViolation("MOOD-EVENT-APPRAISAL-PART-FAILED")
            async with self._factory.unit_of_work() as unit:
                await unit.work.validate_lease(lease)
                current_episode = await self._episodes.context_episode(
                    unit.transaction, episode_id=event.episode_id
                )
                if current_episode != episode:
                    raise MoodViolation("MOOD-EVENT-CONTEXT-STALE")
                subject = await (
                    await unit.transaction.execute(
                        "SELECT subject_version,state_epoch,current_bundle_activation_id "
                        "FROM armi.subjects WHERE subject_id=%s AND status='active' FOR UPDATE",
                        (event.subject_id,),
                    )
                ).fetchone()
                if subject is None or tuple(subject) != (
                    version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                ):
                    raise MoodViolation("MOOD-EVENT-SUBJECT-STALE")
                now = datetime.now(UTC)
                await self._episodes.accept_mood(
                    unit.transaction,
                    episode_id=event.episode_id,
                    assessment_id=assessment.assessment_id,
                    previous_subject_version=episode.base_subject_version,
                    subject_version=version,
                )
                await unit.work.enqueue(
                    WorkDraft(
                        WorkId(uuid7()),
                        WorkType.COGNITION_CONTEXT_PREPARE,
                        WorkOwner("cognitive_episode", event.episode_id),
                        IdempotencyKey(f"context:{event.episode_id}"),
                        Digest.from_bytes(compiled_context),
                        50,
                        Instant(now),
                        Instant(now + timedelta(hours=1)),
                        1,
                        episode.trace_id,
                        SubjectId(event.subject_id),
                        WorkPayloadRef("cognitive_episode", event.episode_id),
                    )
                )
                await unit.work.complete(
                    lease, WorkResultRef("cognitive_episode", event.episode_id)
                )
            record_diagnostic(
                "appraisal.completed",
                component="appraisal",
                assessment_id=assessment.assessment_id,
                subject_version=version,
            )
        except BaseException as error:
            # Cleanup the dispatched receipt without ever repeating the model call.
            async with self._factory.unit_of_work() as unit:
                await self._store.fail(
                    unit.transaction,
                    assessment_id=assessment.assessment_id,
                    code=getattr(
                        error,
                        "code",
                        "MOOD-EVALUATION-INTERRUPTED"
                        if isinstance(error, asyncio.CancelledError)
                        else "MOOD-EVALUATION-FAILED",
                    ),
                    interrupted=isinstance(error, asyncio.CancelledError),
                )
            raise
