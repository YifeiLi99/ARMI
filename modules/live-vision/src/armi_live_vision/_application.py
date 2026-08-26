"""Durable private observation around the single visual-model call."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityPurpose,
)
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    DurableWorkPort,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
    WorkType,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_perception.api import (
    ExternalContentRecognitionStatus,
    VisualRecognitionAttemptPort,
    VisualRecognitionInput,
    VisualRecognitionPort,
    VisualRecognitionRequest,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from .api import (
    CameraDevice,
    CameraFrame,
    ObservationStatus,
    ObservationTrigger,
    VisualObservation,
)


class DurableVisualObservationCoordinator:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogPort,
        work: DurableWorkPort,
        recognizer: VisualRecognitionPort,
        attempts: VisualRecognitionAttemptPort,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
        subject_id: UUID,
        device: CameraDevice,
        retention: timedelta = timedelta(hours=24),
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._catalog = catalog
        self._work = work
        self._recognizer = recognizer
        self._attempts = attempts
        self._evidence = evidence
        self._opportunity = opportunity
        self._subject_id = subject_id
        self._device = device
        self._retention = retention
        self._session_id: UUID | None = None
        self._number = 0
        self._previous_summary: str | None = None
        self._worker_id = uuid7()
        self._stop = asyncio.Event()

    async def open_session(self) -> None:
        await self._storage.prepare()
        await self.purge_expired_frames()
        self._session_id = uuid7()
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_vision_sessions
                   (session_id,subject_id,state,device_name,device_path,usb_location_id,backend,width,height,fps)
                   VALUES (%s,%s,'observing',%s,%s,%s,'DSHOW',1280,720,5)""",
                (
                    self._session_id,
                    self._subject_id,
                    self._device.name,
                    self._device.device_path,
                    self._device.usb_location_id,
                ),
            )

    async def close_session(self, *, error_code: str | None = None) -> None:
        if self._session_id is None:
            return
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """UPDATE armi.live_vision_sessions SET state=%s,ended_at=statement_timestamp(),error_code=%s
                   WHERE session_id=%s AND ended_at IS NULL""",
                ("failed" if error_code else "stopped", error_code, self._session_id),
            )
        self._session_id = None

    async def settle_interrupted_observations(self, *, error_code: str) -> None:
        if self._session_id is None:
            return
        async with self._factory.unit_of_work() as unit:
            observation_rows = await (
                await unit.transaction.execute(
                    """UPDATE armi.live_vision_observations
                       SET status='unknown',error_code=%s,
                           settled_at=statement_timestamp()
                       WHERE session_id=%s AND status='recognizing'
                       RETURNING observation_id""",
                    (error_code, self._session_id),
                )
            ).fetchall()
            if observation_rows:
                await self._attempts.settle_interrupted(
                    unit,
                    observation_ids=tuple(row[0] for row in observation_rows),
                    error_code=error_code,
                )

    async def purge_expired_frames(self) -> int:
        async with self._factory.unit_of_work() as unit:
            rows = await (
                await unit.transaction.execute(
                    """SELECT artifact_id FROM armi.live_vision_observation_frames
                       WHERE artifact_id IS NOT NULL AND purge_after<=statement_timestamp()
                       ORDER BY purge_after FOR UPDATE"""
                )
            ).fetchall()
            if rows:
                await unit.transaction.execute(
                    """UPDATE armi.live_vision_observation_frames
                       SET artifact_id=NULL,purged_at=statement_timestamp()
                       WHERE artifact_id IS NOT NULL AND purge_after<=statement_timestamp()"""
                )
                for row in rows:
                    await self._catalog.retire_artifact(unit, ArtifactId(row[0]))
        return len(rows)

    async def get_observation_by_key(
        self, idempotency_key: str
    ) -> VisualObservation | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT observation_id,trigger_kind,status,registered_at,"
                    "change_score,scene_summary,error_code "
                    "FROM armi.live_vision_observations WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
            ).fetchone()
        return None if row is None else _observation_from_row(row)

    async def observe(
        self,
        *,
        trigger: ObservationTrigger,
        frames: tuple[CameraFrame, ...],
        change_score: float | None,
        idempotency_key: str | None = None,
    ) -> VisualObservation:
        await self.purge_expired_frames()
        if self._session_id is None:
            raise RuntimeError("live vision session is not open")
        selected_frames = frames[:4]
        request_document: dict[str, object] = {
            "schema_version": "creator-live-vision-observation-request.v1",
            "trigger": trigger.value,
        }
        if trigger is not ObservationTrigger.MANUAL:
            request_document["frame_digests"] = [
                Digest.from_bytes(frame.jpeg).value for frame in selected_frames
            ]
            request_document["change_score"] = change_score
        request_bytes = json.dumps(
            request_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        request_digest = Digest.from_bytes(request_bytes)
        key = idempotency_key or f"auto:{self._session_id}:{uuid7()}"
        async with self._factory.unit_of_work(read_only=True) as unit:
            existing = await (
                await unit.transaction.execute(
                    "SELECT observation_id,trigger_kind,status,registered_at,"
                    "change_score,scene_summary,error_code,request_digest "
                    "FROM armi.live_vision_observations WHERE idempotency_key=%s",
                    (key,),
                )
            ).fetchone()
        if existing is not None:
            if str(existing[7]) != request_digest.value:
                raise RuntimeError("VISION-IDEMPOTENCY-CONFLICT")
            return _observation_from_row(existing)
        observation_id, attempt_id, work_id = uuid7(), uuid7(), uuid7()
        trace_id = TraceId(uuid7().hex)
        registered_at = datetime.now(UTC)
        published_frames = [
            (
                frame,
                await self._publish(
                    frame.jpeg, "image/jpeg", "live.vision.selected-frame", trace_id
                ),
            )
            for frame in selected_frames
        ]
        published_request = await self._publish(
            request_bytes,
            "application/json",
            "live.vision.recognition-request",
            trace_id,
        )
        async with self._factory.unit_of_work() as unit:
            session = await (
                await unit.transaction.execute(
                    "SELECT session_id FROM armi.live_vision_sessions "
                    "WHERE session_id=%s AND ended_at IS NULL FOR UPDATE",
                    (self._session_id,),
                )
            ).fetchone()
            if session is None:
                raise RuntimeError("VISION-SESSION-CLOSED")
            prior = await (
                await unit.transaction.execute(
                    "SELECT observation_id,request_digest FROM "
                    "armi.live_vision_observations WHERE idempotency_key=%s",
                    (key,),
                )
            ).fetchone()
            if prior is not None:
                if str(prior[1]) != request_digest.value:
                    raise RuntimeError("VISION-IDEMPOTENCY-CONFLICT")
                existing = await (
                    await unit.transaction.execute(
                        "SELECT observation_id,trigger_kind,status,registered_at,"
                        "change_score,scene_summary,error_code FROM "
                        "armi.live_vision_observations WHERE observation_id=%s",
                        (prior[0],),
                    )
                ).fetchone()
                if existing is None:
                    raise RuntimeError("VISION-IDEMPOTENCY-RACE")
                return _observation_from_row(existing)
            number_row = await (
                await unit.transaction.execute(
                    "SELECT COALESCE(max(observation_no),0)+1 FROM "
                    "armi.live_vision_observations WHERE session_id=%s",
                    (self._session_id,),
                )
            ).fetchone()
            if number_row is None:
                raise RuntimeError("VISION-OBSERVATION-NUMBER")
            self._number = int(number_row[0])
            await unit.work.enqueue(
                WorkDraft(
                    WorkId(work_id),
                    WorkType.LIVE_VISION_OBSERVE,
                    WorkOwner("live_vision_observation", observation_id),
                    IdempotencyKey(key),
                    request_digest,
                    50,
                    Instant(registered_at),
                    Instant(registered_at + timedelta(minutes=10)),
                    2,
                    trace_id,
                    subject_id=SubjectId(self._subject_id),
                    payload=WorkPayloadRef("live_vision_observation", observation_id),
                )
            )
            await unit.transaction.execute(
                """INSERT INTO armi.live_vision_observations
                   (observation_id,session_id,subject_id,observation_no,trigger_kind,
                    idempotency_key,request_digest,work_id,status,change_score)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'registered',%s)""",
                (
                    observation_id,
                    self._session_id,
                    self._subject_id,
                    self._number,
                    trigger.value,
                    key,
                    request_digest.value,
                    work_id,
                    change_score,
                ),
            )
            for ordinal, (frame, published) in enumerate(published_frames, start=1):
                registration = await self._catalog.register(
                    unit, ArtifactId(uuid7()), published
                )
                await unit.transaction.execute(
                    """INSERT INTO armi.live_vision_observation_frames
                       (observation_id,ordinal,artifact_id,content_digest,byte_size,width,height,captured_at,purge_after)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        observation_id,
                        ordinal,
                        registration.ref.artifact_id.value,
                        registration.ref.content_digest.value,
                        registration.ref.byte_size,
                        frame.width,
                        frame.height,
                        frame.captured_at,
                        frame.captured_at + self._retention,
                    ),
                )
            request_registration = await self._catalog.register(
                unit, ArtifactId(uuid7()), published_request
            )
            await self._attempts.begin(
                unit,
                attempt_id=attempt_id,
                observation_id=observation_id,
                request_artifact_id=request_registration.ref.artifact_id.value,
                provider="volcengine_ark",
                model_id="doubao-seed-2-0-lite-260428",
            )
        return VisualObservation(
            observation_id,
            trigger,
            ObservationStatus.REGISTERED,
            registered_at,
            change_score,
        )

    async def process_once(self) -> bool:
        records = await self._work.claim(
            work_kind=WorkType.LIVE_VISION_OBSERVE,
            lease_owner=self._worker_id,
            lease_seconds=60,
        )
        if not records:
            return False
        record = records[0]
        lease = record.lease
        if lease is None:
            raise RuntimeError("VISION-WORK-LEASE")
        async with self._factory.unit_of_work() as unit:
            await unit.work.validate_lease(lease)
            row = await (
                await unit.transaction.execute(
                    "SELECT observation.observation_id,observation.trigger_kind,"
                    "observation.change_score,observation.registered_at "
                    "FROM armi.live_vision_observations AS observation "
                    "WHERE observation.observation_id=%s AND observation.work_id=%s "
                    "AND observation.status='registered' FOR UPDATE",
                    (record.draft.owner.reference, record.draft.work_id.value),
                )
            ).fetchone()
            attempt_id = (
                None
                if row is None
                else await self._attempts.prepared_attempt_for_observation(
                    unit, observation_id=UUID(str(row[0]))
                )
            )
            if row is None or attempt_id is None:
                await unit.work.complete(
                    lease,
                    WorkResultRef(
                        "live_vision_observation", record.draft.owner.reference
                    ),
                )
                return True
            frame_rows = await (
                await unit.transaction.execute(
                    "SELECT frame.artifact_id,frame.width,frame.height,frame.captured_at "
                    "FROM armi.live_vision_observation_frames AS frame "
                    "WHERE frame.observation_id=%s ORDER BY frame.ordinal",
                    (row[0],),
                )
            ).fetchall()
            refs = [
                await self._catalog.get(unit, ArtifactId(item[0]))
                for item in frame_rows
            ]
            await self._attempts.mark_dispatched(unit, attempt_id=attempt_id)
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations SET status='recognizing' "
                "WHERE observation_id=%s AND status='registered'",
                (row[0],),
            )
        frame_values: list[CameraFrame] = []
        for item, ref in zip(frame_rows, refs, strict=True):
            value = b""
            async with await self._storage.open_verified(ref) as stream:
                value = await stream.read()
            frame_values.append(CameraFrame(item[3], value, int(item[1]), int(item[2])))
        previous = await self._previous_completed_summary()
        try:
            result = await self._recognizer.recognize_visual(
                VisualRecognitionRequest(
                    row[0],
                    str(row[1]),
                    tuple(
                        VisualRecognitionInput(frame.jpeg, Instant(frame.captured_at))
                        for frame in frame_values
                    ),
                    previous,
                    record.draft.trace_id,
                )
            )
        except Exception:
            await self._settle_failure(
                row[0],
                attempt_id,
                ObservationStatus.UNKNOWN,
                "VISION-OUTCOME-UNKNOWN",
                lease=lease,
            )
            return True
        if result.status is not ExternalContentRecognitionStatus.SUCCEEDED:
            status = (
                ObservationStatus.UNKNOWN
                if result.status is ExternalContentRecognitionStatus.UNKNOWN
                else ObservationStatus.FAILED
            )
            await self._settle_failure(
                row[0],
                attempt_id,
                status,
                result.error_code or "VISION-MODEL-FAILED",
                lease=lease,
            )
            return True
        assert (
            result.raw_response is not None
            and result.scene_summary is not None
            and result.change_class is not None
        )
        published_response = await self._publish(
            result.raw_response,
            "application/json",
            "live.vision.recognition-response",
            record.draft.trace_id,
        )
        evidence_id = EvidenceId(uuid7())
        async with self._factory.unit_of_work() as unit:
            response_registration = await self._catalog.register(
                unit, ArtifactId(uuid7()), published_response
            )
            await self._evidence.accept(
                unit,
                EvidenceDraft(
                    evidence_id=evidence_id,
                    subject_id=self._subject_id,
                    scene_id=None,
                    context_party_id=None,
                    artifact_id=response_registration.ref.artifact_id.value,
                    source_kind=EvidenceSourceKind.VISUAL_OBSERVATION,
                    privacy_scope=EvidencePrivacyScope.PRIVATE,
                    visual_observation_id=row[0],
                ),
            )
            await self._attempts.settle(
                unit,
                attempt_id=attempt_id,
                status="succeeded",
                response_artifact_id=response_registration.ref.artifact_id.value,
                provider_request_id=result.provider_request_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                error_code=None,
            )
            await unit.transaction.execute(
                """UPDATE armi.live_vision_observations SET status='completed',change_class=%s,scene_summary=%s,
                   visible_change=%s,uncertainty=%s,provider=%s,model_id=%s,input_tokens=%s,output_tokens=%s,
                   evidence_id=%s,settled_at=statement_timestamp() WHERE observation_id=%s AND status='recognizing'""",
                (
                    result.change_class.value,
                    result.scene_summary,
                    result.visible_change,
                    "\uff1b".join(result.uncertainties) or None,
                    result.provider,
                    result.model_id,
                    result.input_tokens,
                    result.output_tokens,
                    evidence_id.value,
                    row[0],
                ),
            )
            if (
                ObservationTrigger(str(row[1]))
                in {ObservationTrigger.INITIAL, ObservationTrigger.MANUAL}
                or result.change_class.value == "notable"
            ):
                await self._opportunity.admit_external_evidence(
                    unit.transaction,
                    ExternalEvidenceOpportunityDraft(
                        evidence_id.value,
                        self._subject_id,
                        None,
                        None,
                        OpportunityPurpose.CONSIDER_VISUAL_OBSERVATION,
                    ),
                )
            await unit.work.validate_lease(lease)
            await unit.work.complete(
                lease, WorkResultRef("live_vision_observation", row[0])
            )
        self._previous_summary = result.scene_summary
        return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            if await self.process_once():
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    def stop_worker(self) -> None:
        self._stop.set()

    async def get_observation(self, observation_id: UUID) -> VisualObservation | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT observation_id,trigger_kind,status,registered_at,"
                    "change_score,scene_summary,error_code FROM "
                    "armi.live_vision_observations WHERE observation_id=%s",
                    (observation_id,),
                )
            ).fetchone()
        return None if row is None else _observation_from_row(row)

    async def _previous_completed_summary(self) -> str | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT scene_summary FROM armi.live_vision_observations "
                    "WHERE subject_id=%s AND status='completed' "
                    "ORDER BY settled_at DESC LIMIT 1",
                    (self._subject_id,),
                )
            ).fetchone()
        return None if row is None else str(row[0])

    async def _settle_failure(
        self,
        observation_id: UUID,
        attempt_id: UUID,
        status: ObservationStatus,
        code: str,
        *,
        lease: WorkLease,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            await self._attempts.settle(
                unit,
                attempt_id=attempt_id,
                status=status.value,
                response_artifact_id=None,
                provider_request_id=None,
                input_tokens=None,
                output_tokens=None,
                error_code=code,
            )
            await unit.transaction.execute(
                """UPDATE armi.live_vision_observations SET status=%s,error_code=%s,settled_at=statement_timestamp()
                   WHERE observation_id=%s""",
                (status.value, code, observation_id),
            )
            await unit.work.validate_lease(lease)
            await unit.work.complete(
                lease, WorkResultRef("live_vision_observation", observation_id)
            )

    async def _publish(
        self, value: bytes, media_type: str, logical_kind: str, trace_id: TraceId
    ):
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                media_type,
                logical_kind,
                "live.vision",
                trace_id,
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)


class LiveVisionRetentionCoordinator:
    """Expire frame logical artifacts even when camera capability is disabled."""

    __slots__ = ("_catalog", "_factory", "_stop")

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        catalog: ArtifactCatalogPort,
    ) -> None:
        self._factory = factory
        self._catalog = catalog
        self._stop = asyncio.Event()

    async def purge_once(self) -> int:
        async with self._factory.unit_of_work() as unit:
            rows = await (
                await unit.transaction.execute(
                    """SELECT observation_id,ordinal,artifact_id
                       FROM armi.live_vision_observation_frames
                       WHERE artifact_id IS NOT NULL
                         AND purge_after<=statement_timestamp()
                       ORDER BY purge_after,observation_id,ordinal
                       FOR UPDATE SKIP LOCKED"""
                )
            ).fetchall()
            for observation_id, ordinal, artifact_id in rows:
                await self._catalog.retire_artifact(unit, ArtifactId(artifact_id))
                await unit.transaction.execute(
                    """UPDATE armi.live_vision_observation_frames
                       SET artifact_id=NULL,purged_at=statement_timestamp()
                       WHERE observation_id=%s AND ordinal=%s AND artifact_id=%s""",
                    (observation_id, ordinal, artifact_id),
                )
        return len(rows)

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.purge_once()
            async with self._factory.unit_of_work(read_only=True) as unit:
                row = await (
                    await unit.transaction.execute(
                        """SELECT min(purge_after)
                           FROM armi.live_vision_observation_frames
                           WHERE artifact_id IS NOT NULL"""
                    )
                ).fetchone()
            delay = 60.0
            if row is not None and row[0] is not None:
                delay = max(
                    0.1,
                    min(60.0, (row[0] - datetime.now(UTC)).total_seconds()),
                )
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)

    def stop(self) -> None:
        self._stop.set()


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _observation_from_row(row: Sequence[object]) -> VisualObservation:
    observation_id = UUID(str(row[0]))
    registered_at = row[3]
    if not isinstance(registered_at, datetime):
        raise RuntimeError("VISION-OBSERVATION-ROW")
    return VisualObservation(
        observation_id,
        ObservationTrigger(str(row[1])),
        ObservationStatus(str(row[2])),
        registered_at,
        None if row[4] is None else float(str(row[4])),
        None if row[5] is None else str(row[5]),
        None if row[6] is None else str(row[6]),
    )


__all__ = ("DurableVisualObservationCoordinator", "LiveVisionRetentionCoordinator")
