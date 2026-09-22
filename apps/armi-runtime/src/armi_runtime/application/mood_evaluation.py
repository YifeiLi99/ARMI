"""Commit event appraisal before freezing the main cognition Context."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_cognition.api import CognitionContextLifecyclePort
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
    provider_meter_scope,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId
from armi_mood.api import (
    MoodAppraiserPort,
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
        store: MoodEventStorePort,
        appraiser: MoodAppraiserPort,
        prices: PriceCatalog,
    ) -> None:
        self._factory = factory
        self._episodes = episodes
        self._store = store
        self._appraiser = appraiser
        self._prices = prices

    async def evaluate(
        self, *, event: MoodEvent, lease: WorkLease, compiled_context: bytes
    ) -> None:
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

        try:
            result = None
            if assessment.status == "new":
                with provider_meter_scope(
                    ProviderMeterScope(save_usage, self._prices, "mood.evaluate")
                ):
                    result = await self._appraiser.evaluate(
                        assessment=assessment,
                        context=json.loads(compiled_context),
                    )
            async with self._factory.unit_of_work() as unit:
                await unit.work.validate_lease(lease)
                current_episode = await self._episodes.context_episode(
                    unit.transaction, episode_id=event.episode_id
                )
                if current_episode != episode:
                    raise MoodViolation("MOOD-CONTEXT-STALE")
                subject = await (
                    await unit.transaction.execute(
                        """SELECT subject_version,state_epoch,current_bundle_activation_id
                       FROM armi.subjects WHERE subject_id=%s AND status='active' FOR UPDATE""",
                        (event.subject_id,),
                    )
                ).fetchone()
                if subject is None or tuple(subject) != (
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                ):
                    raise MoodViolation("MOOD-SUBJECT-STALE")
                now = datetime.now(UTC)
                changed = result is not None and await self._store.apply(
                    unit.transaction,
                    assessment=assessment,
                    result=result,
                    at=now,
                )
                version = episode.base_subject_version + int(changed)
                if changed:
                    await unit.transaction.execute(
                        "UPDATE armi.subjects SET subject_version=%s WHERE subject_id=%s",
                        (version, event.subject_id),
                    )
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
