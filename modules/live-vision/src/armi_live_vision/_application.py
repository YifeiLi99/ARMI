"""Durable private observation around the single visual-model call."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TypedDict, cast
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
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
    WorkResultRef,
    WorkType,
    provider_meter_scope,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_perception.api import (
    ExternalContentRecognitionStatus,
    VisualRecognitionInput,
    VisualRecognitionPort,
    VisualRecognitionRequest,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from .api import (
    CameraSourceIdentity,
    LiveVisionViolation,
    ObservationOriginKind,
    ObservationStatus,
    ObservationTrigger,
    VisualFrame,
    VisualObservation,
    VisualSourceIdentity,
    VisualSourceKind,
)


class _FrameDocument(TypedDict):
    ordinal: int
    artifact_id: str | None
    content_digest: str
    byte_size: int
    width: int
    height: int
    captured_at: str
    purge_after: str
    purged_at: str | None


class DurableVisualObservationCoordinator:
    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogPort,
        work: DurableWorkPort,
        recognizer: VisualRecognitionPort,
        prices: PriceCatalog,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
        subject_id: UUID,
        source_kind: VisualSourceKind,
        source: VisualSourceIdentity,
        width: int,
        height: int,
        fps: float,
        retention: timedelta = timedelta(hours=24),
        diagnostic: Callable[[str, UUID, str | None], None] | None = None,
        failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
    ) -> None:
        self._factory = factory
        self._diagnostic = diagnostic
        self._failure_notification = failure_notification
        self._storage = storage
        self._catalog = catalog
        self._work = work
        self._recognizer = recognizer
        self._prices = prices
        self._evidence = evidence
        self._opportunity = opportunity
        self._subject_id = subject_id
        self._source_kind = source_kind
        self._source = source
        self._width = width
        self._height = height
        self._fps = fps
        self._retention = retention
        self._session_lock = asyncio.Lock()
        self._session_id: UUID | None = None
        self._number = 0
        self._previous_summary: str | None = None
        self._worker_id = uuid7()
        self._stop = asyncio.Event()
        self._capture: Callable[[], Awaitable[tuple[VisualFrame, ...]]] | None = None

    def bind_capture(
        self, capture: Callable[[], Awaitable[tuple[VisualFrame, ...]]]
    ) -> None:
        self._capture = capture

    async def open_session(self) -> None:
        await self._storage.prepare()
        await self.purge_expired_frames()
        async with self._session_lock:
            if self._session_id is not None:
                raise RuntimeError("VISION-SESSION-ALREADY-OPEN")
            self._session_id = uuid7()
            logging.getLogger(__name__).info(
                "live vision session opened",
                extra={
                    "session_id": str(self._session_id),
                    "source_kind": self._source_kind.value,
                    "source_identity": _source_identity_document(self._source),
                    "width": self._width,
                    "height": self._height,
                    "fps": self._fps,
                },
            )

    async def close_session(self, *, error_code: str | None = None) -> None:
        async with self._session_lock:
            if self._session_id is None:
                return
            logging.getLogger(__name__).info(
                "live vision session closed",
                extra={"session_id": str(self._session_id), "error_code": error_code},
            )
            self._session_id = None

    async def settle_interrupted_observations(self, *, error_code: str) -> None:
        session_id = self._session_id
        if session_id is None:
            return
        async with self._factory.unit_of_work() as unit:
            observation_rows = await (
                await unit.transaction.execute(
                    """UPDATE armi.live_vision_observations
                       SET status='unknown',error_code=%s,
                           settled_at=statement_timestamp()
                       WHERE session_id=%s AND status='recognizing'
                       RETURNING observation_id""",
                    (error_code, session_id),
                )
            ).fetchall()
        for row in observation_rows:
            self._log("interrupted", row[0], error_code)

    async def purge_expired_frames(self) -> int:
        return await _purge_frames(self._factory, self._catalog)

    async def get_observation_by_key(
        self, idempotency_key: str
    ) -> VisualObservation | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT observation_id,source_kind,origin_kind,trigger_kind,status,registered_at,"
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
        frames: tuple[VisualFrame, ...],
        change_score: float | None,
        origin_kind: ObservationOriginKind,
        idempotency_key: str | None = None,
        origin_episode_id: UUID | None = None,
        origin_scene_id: UUID | None = None,
    ) -> VisualObservation:
        await self.purge_expired_frames()
        session_id = self._session_id
        if session_id is None:
            raise RuntimeError("live vision session is not open")
        if frames:
            raise RuntimeError("VISION-CAPTURE-MUST-BE-DURABLE")
        request_document: dict[str, object] = {
            "schema_version": "armi.visual-capture-request.v1",
            "source_kind": self._source_kind.value,
            "origin_kind": origin_kind.value,
            "trigger": trigger.value,
            "change_score": change_score,
        }
        request_bytes = json.dumps(
            request_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        request_digest = Digest.from_bytes(request_bytes)
        key = idempotency_key or f"auto:{session_id}:{uuid7()}"
        async with self._factory.unit_of_work(read_only=True) as unit:
            existing = await (
                await unit.transaction.execute(
                    "SELECT observation_id,source_kind,origin_kind,trigger_kind,status,registered_at,"
                    "change_score,scene_summary,error_code,request_digest "
                    "FROM armi.live_vision_observations WHERE idempotency_key=%s",
                    (key,),
                )
            ).fetchone()
        if existing is not None:
            if str(existing[9]) != request_digest.value:
                raise RuntimeError("VISION-IDEMPOTENCY-CONFLICT")
            return _observation_from_row(existing)
        observation_id, work_id = uuid7(), uuid7()
        trace_id = TraceId(uuid7().hex)
        registered_at = datetime.now(UTC)
        async with self._session_lock, self._factory.unit_of_work() as unit:
            if self._session_id != session_id:
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
                        "SELECT observation_id,source_kind,origin_kind,trigger_kind,status,registered_at,"
                        "change_score,scene_summary,error_code FROM "
                        "armi.live_vision_observations WHERE observation_id=%s",
                        (prior[0],),
                    )
                ).fetchone()
                if existing is None:
                    raise RuntimeError("VISION-IDEMPOTENCY-RACE")
                return _observation_from_row(existing)
            await unit.work.enqueue(
                WorkDraft(
                    WorkId(work_id),
                    WorkType.LIVE_VISION_CAPTURE,
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
                   (observation_id,subject_id,source_kind,origin_kind,trigger_kind,
                    origin_episode_id,origin_scene_id,idempotency_key,request_digest,capture_work_id,status,change_score)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'capture_pending',%s)""",
                (
                    observation_id,
                    self._subject_id,
                    self._source_kind.value,
                    origin_kind.value,
                    trigger.value,
                    origin_episode_id,
                    origin_scene_id,
                    key,
                    request_digest.value,
                    work_id,
                    change_score,
                ),
            )
        return VisualObservation(
            observation_id,
            self._source_kind,
            origin_kind,
            trigger,
            ObservationStatus.CAPTURE_PENDING,
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
                    "SELECT observation.observation_id,observation.trigger_kind,observation.source_kind,"
                    "observation.origin_kind,observation.change_score,observation.registered_at,"
                    "observation.origin_scene_id,observation.origin_context_party_id "
                    "FROM armi.live_vision_observations AS observation "
                    "WHERE observation.observation_id=%s AND observation.recognition_work_id=%s "
                    "AND observation.status='registered' FOR UPDATE",
                    (record.draft.owner.reference, record.draft.work_id.value),
                )
            ).fetchone()
            if row is None:
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
                    "FROM armi.live_vision_observations AS observation, "
                    "jsonb_to_recordset(observation.frames) AS frame(ordinal int, artifact_id uuid, width int, height int, captured_at timestamptz) "
                    "WHERE observation.observation_id=%s ORDER BY frame.ordinal",
                    (row[0],),
                )
            ).fetchall()
            refs = [
                await self._catalog.get(unit, ArtifactId(item[0]))
                for item in frame_rows
            ]
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations SET status='recognizing' "
                "WHERE observation_id=%s AND status='registered'",
                (row[0],),
            )
        self._log("dispatched", row[0])
        frame_values: list[VisualFrame] = []
        for item, ref in zip(frame_rows, refs, strict=True):
            value = b""
            async with await self._storage.open_verified(ref) as stream:
                value = await stream.read()
            frame_values.append(VisualFrame(item[3], value, int(item[1]), int(item[2])))
        previous = await self._previous_completed_summary(VisualSourceKind(str(row[2])))
        try:

            async def save(receipt: ProviderCallReceipt) -> None:
                # DESIGN.md: interrupted observations accept only receipts for existing calls.
                async with self._factory.provider_usage_unit_of_work(
                    receipt=receipt
                ) as unit:
                    update = await unit.transaction.execute(
                        """UPDATE armi.live_vision_observations
                           SET provider_calls=jsonb_set(provider_calls,ARRAY[%s],%s::jsonb)
                           WHERE observation_id=%s
                             AND ((%s AND status='recognizing' AND NOT (provider_calls ? %s))
                                  OR (NOT %s AND provider_calls ? %s))""",
                        (
                            receipt.call_id,
                            json.dumps(receipt.document()),
                            row[0],
                            receipt.registration,
                            receipt.call_id,
                            receipt.registration,
                            receipt.call_id,
                        ),
                    )
                    if update.rowcount != 1:
                        raise LiveVisionViolation(
                            "VISION-USAGE-STALE", "视觉用量回执不属于当前调用"
                        )

            with provider_meter_scope(
                ProviderMeterScope(save, self._prices, "visual_observation")
            ):
                result = await self._recognizer.recognize_visual(
                    VisualRecognitionRequest(
                        row[0],
                        str(row[1]),
                        str(row[2]),
                        tuple(
                            VisualRecognitionInput(
                                frame.jpeg, Instant(frame.captured_at)
                            )
                            for frame in frame_values
                        ),
                        previous,
                        record.draft.trace_id,
                    )
                )
        except Exception:
            await self._settle_failure(
                row[0],
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
                    scene_id=row[6],
                    context_party_id=row[7],
                    artifact_id=response_registration.ref.artifact_id.value,
                    source_kind=EvidenceSourceKind.VISUAL_OBSERVATION,
                    privacy_scope=EvidencePrivacyScope.PRIVATE,
                    visual_observation_id=row[0],
                ),
            )
            await unit.transaction.execute(
                """UPDATE armi.live_vision_observations SET status='completed',change_class=%s,scene_summary=%s,
                   visible_change=%s,uncertainty=%s,provider=%s,model_id=%s,input_tokens=%s,output_tokens=%s,
                   evidence_id=%s,response_artifact_id=%s,provider_request_id=%s,
                   settled_at=statement_timestamp() WHERE observation_id=%s AND status='recognizing'""",
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
                    response_registration.ref.artifact_id.value,
                    result.provider_request_id,
                    row[0],
                ),
            )
            if (
                ObservationTrigger(str(row[1]))
                in {
                    ObservationTrigger.INITIAL,
                    ObservationTrigger.MANUAL,
                    ObservationTrigger.SUBJECT_REQUEST,
                }
                or result.change_class.value == "notable"
            ):
                await self._opportunity.admit_external_evidence(
                    unit.transaction,
                    ExternalEvidenceOpportunityDraft(
                        evidence_id.value,
                        self._subject_id,
                        row[6],
                        row[7],
                        OpportunityPurpose.CONSIDER_REQUESTED_VISUAL_OBSERVATION
                        if row[6] is not None
                        else OpportunityPurpose.CONSIDER_VISUAL_OBSERVATION,
                    ),
                )
            await unit.work.validate_lease(lease)
            await unit.work.complete(
                lease, WorkResultRef("live_vision_observation", row[0])
            )
        self._log("completed", row[0])
        self._previous_summary = result.scene_summary
        return True

    async def process_capture_once(self) -> bool:
        records = await self._work.claim(
            work_kind=WorkType.LIVE_VISION_CAPTURE,
            lease_owner=self._worker_id,
            lease_seconds=30,
        )
        if not records:
            return False
        await self.process_claimed_capture(records[0])
        return True

    async def process_claimed_capture(self, record: WorkRecord) -> None:
        session_id = self._session_id
        lease = record.lease
        if lease is None:
            raise RuntimeError("VISION-CAPTURE-WORK-LEASE")
        observation_id = record.draft.owner.reference
        async with self._factory.unit_of_work() as unit:
            await unit.work.validate_lease(lease)
            row = await (
                await unit.transaction.execute(
                    """SELECT source_kind,origin_kind,trigger_kind,origin_episode_id,
                              origin_scene_id,origin_context_party_id,change_score,idempotency_key
                       FROM armi.live_vision_observations
                       WHERE observation_id=%s AND capture_work_id=%s
                         AND status='capture_pending' FOR UPDATE""",
                    (observation_id, record.draft.work_id.value),
                )
            ).fetchone()
            if row is None:
                await unit.work.complete(
                    lease, WorkResultRef("live_vision_observation", observation_id)
                )
                return
            unavailable = (
                str(row[0]) != self._source_kind.value or self._capture is None
            )
            if unavailable:
                await unit.transaction.execute(
                    "UPDATE armi.live_vision_observations SET status='failed',error_code='VISION-SOURCE-UNAVAILABLE',settled_at=statement_timestamp() WHERE observation_id=%s",
                    (observation_id,),
                )
                await unit.work.complete(
                    lease, WorkResultRef("live_vision_observation", observation_id)
                )
            else:
                await unit.transaction.execute(
                    "UPDATE armi.live_vision_observations SET status='capturing' WHERE observation_id=%s",
                    (observation_id,),
                )
        if unavailable:
            await self._notify_failure(observation_id, "VISION-SOURCE-UNAVAILABLE")
            return
        assert self._capture is not None
        try:
            # Closing waits for an active capture; reopening cannot adopt its frames.
            async with self._session_lock:
                if session_id is None or self._session_id != session_id:
                    raise LiveVisionViolation(
                        "VISION-SOURCE-NOT-RUNNING", "source session closed"
                    )
                frames = await self._capture()
            await self._attach_captured_frames(
                observation_id=observation_id,
                session_id=session_id,
                frames=frames,
                origin_kind=ObservationOriginKind(str(row[1])),
                trigger=ObservationTrigger(str(row[2])),
                origin_episode_id=row[3],
                origin_scene_id=row[4],
                origin_context_party_id=row[5],
                change_score=None if row[6] is None else float(row[6]),
                idempotency_key=str(row[7]),
                capture_lease=lease,
            )
        except Exception as error:
            code = getattr(error, "code", "VISION-CAPTURE-FAILED")
            async with self._factory.unit_of_work() as unit:
                await unit.transaction.execute(
                    "UPDATE armi.live_vision_observations SET status='failed',error_code=%s,settled_at=statement_timestamp() WHERE observation_id=%s AND status='capturing'",
                    (code, observation_id),
                )
                await unit.work.validate_lease(lease)
                await unit.work.complete(
                    lease, WorkResultRef("live_vision_observation", observation_id)
                )

            self._log("failed", observation_id, code)
            await self._notify_failure(observation_id, code)

    async def _notify_failure(self, observation_id: UUID, code: str) -> None:
        if self._failure_notification is not None and not self._stop.is_set():
            await self._failure_notification(observation_id, code)

    async def run_recognition_worker(self) -> None:
        while not self._stop.is_set():
            if await self.process_once():
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    async def _attach_captured_frames(
        self,
        *,
        observation_id: UUID,
        session_id: UUID,
        frames: tuple[VisualFrame, ...],
        origin_kind: ObservationOriginKind,
        trigger: ObservationTrigger,
        origin_episode_id: UUID | None,
        origin_scene_id: UUID | None,
        origin_context_party_id: UUID | None,
        change_score: float | None,
        idempotency_key: str,
        capture_lease: WorkLease,
    ) -> None:
        if self._session_id != session_id:
            raise LiveVisionViolation(
                "VISION-SOURCE-NOT-RUNNING", "source has no open session"
            )
        selected = frames[:4]
        trace_id = TraceId(uuid7().hex)
        request_bytes = json.dumps(
            {
                "schema_version": "armi.visual-observation-request.v2",
                "source_kind": self._source_kind.value,
                "origin_kind": origin_kind.value,
                "trigger": trigger.value,
                "frame_digests": [
                    Digest.from_bytes(frame.jpeg).value for frame in selected
                ],
                "change_score": change_score,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        published_frames = [
            (
                frame,
                await self._publish(
                    frame.jpeg, "image/jpeg", "live.vision.selected-frame", trace_id
                ),
            )
            for frame in selected
        ]
        published_request = await self._publish(
            request_bytes,
            "application/json",
            "live.vision.recognition-request",
            trace_id,
        )
        work_id = uuid7()
        now = datetime.now(UTC)
        async with self._session_lock, self._factory.unit_of_work() as unit:
            if self._session_id != session_id:
                raise LiveVisionViolation(
                    "VISION-SOURCE-NOT-RUNNING", "source session closed"
                )
            await unit.work.validate_lease(capture_lease)
            number_row = await (
                await unit.transaction.execute(
                    "SELECT COALESCE(max(observation_no),0)+1 FROM armi.live_vision_observations WHERE session_id=%s",
                    (session_id,),
                )
            ).fetchone()
            if number_row is None:
                raise RuntimeError("VISION-OBSERVATION-NUMBER")
            await unit.work.enqueue(
                WorkDraft(
                    WorkId(work_id),
                    WorkType.LIVE_VISION_OBSERVE,
                    WorkOwner("live_vision_observation", observation_id),
                    IdempotencyKey(f"recognize:{idempotency_key}"),
                    Digest.from_bytes(request_bytes),
                    50,
                    Instant(now),
                    Instant(now + timedelta(minutes=10)),
                    2,
                    trace_id,
                    subject_id=SubjectId(self._subject_id),
                    payload=WorkPayloadRef("live_vision_observation", observation_id),
                )
            )
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations SET session_id=%s,observation_no=%s,recognition_work_id=%s,status='registered' WHERE observation_id=%s AND status='capturing'",
                (session_id, int(number_row[0]), work_id, observation_id),
            )
            frames_document: list[_FrameDocument] = []
            for ordinal, (frame, published) in enumerate(published_frames, 1):
                registration = await self._catalog.register(
                    unit, ArtifactId(uuid7()), published
                )
                frames_document.append(
                    {
                        "ordinal": ordinal,
                        "artifact_id": str(registration.ref.artifact_id.value),
                        "content_digest": registration.ref.content_digest.value,
                        "byte_size": registration.ref.byte_size,
                        "width": frame.width,
                        "height": frame.height,
                        "captured_at": frame.captured_at.isoformat(),
                        "purge_after": (
                            frame.captured_at + self._retention
                        ).isoformat(),
                        "purged_at": None,
                    }
                )
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations SET frames=%s::jsonb WHERE observation_id=%s",
                (json.dumps(frames_document), observation_id),
            )
            request_registration = await self._catalog.register(
                unit, ArtifactId(uuid7()), published_request
            )
            await unit.transaction.execute(
                """UPDATE armi.live_vision_observations
                   SET request_artifact_id=%s WHERE observation_id=%s AND status='registered'""",
                (request_registration.ref.artifact_id.value, observation_id),
            )
            await unit.work.complete(
                capture_lease, WorkResultRef("live_vision_observation", observation_id)
            )
        self._log("prepared", observation_id)

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            if await self.process_capture_once():
                continue
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
                    "SELECT observation_id,source_kind,origin_kind,trigger_kind,status,registered_at,"
                    "change_score,scene_summary,error_code FROM "
                    "armi.live_vision_observations WHERE observation_id=%s",
                    (observation_id,),
                )
            ).fetchone()
        return None if row is None else _observation_from_row(row)

    async def _previous_completed_summary(
        self, source_kind: VisualSourceKind
    ) -> str | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT scene_summary FROM armi.live_vision_observations "
                    "WHERE subject_id=%s AND source_kind=%s AND status='completed' "
                    "ORDER BY settled_at DESC LIMIT 1",
                    (self._subject_id, source_kind.value),
                )
            ).fetchone()
        return None if row is None else str(row[0])

    async def _settle_failure(
        self,
        observation_id: UUID,
        status: ObservationStatus,
        code: str,
        *,
        lease: WorkLease,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """UPDATE armi.live_vision_observations SET status=%s,error_code=%s,settled_at=statement_timestamp()
                   WHERE observation_id=%s""",
                (status.value, code, observation_id),
            )
            await unit.work.validate_lease(lease)
            await unit.work.complete(
                lease, WorkResultRef("live_vision_observation", observation_id)
            )

        self._log(status.value, observation_id, code)
        await self._notify_failure(observation_id, code)

    def _log(
        self, event: str, observation_id: UUID, error_code: str | None = None
    ) -> None:
        if self._diagnostic is not None:
            self._diagnostic(event, observation_id, error_code)

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


class VisualCaptureRouter:
    """Claim each capture once and route it to the exact configured source."""

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        work: DurableWorkPort,
        coordinators: Mapping[VisualSourceKind, DurableVisualObservationCoordinator],
        failure_notification: Callable[[UUID, str], Awaitable[None]] | None = None,
    ) -> None:
        self._factory = factory
        self._work = work
        self._coordinators = dict(coordinators)
        self._failure_notification = failure_notification
        self._worker_id = uuid7()
        self._stop = asyncio.Event()

    async def process_once(self) -> bool:
        records = await self._work.claim(
            work_kind=WorkType.LIVE_VISION_CAPTURE,
            lease_owner=self._worker_id,
            lease_seconds=30,
        )
        if not records:
            return False
        record = records[0]
        observation_id = record.draft.owner.reference
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT source_kind FROM armi.live_vision_observations "
                    "WHERE observation_id=%s AND capture_work_id=%s",
                    (observation_id, record.draft.work_id.value),
                )
            ).fetchone()
        coordinator = (
            None
            if row is None
            else self._coordinators.get(VisualSourceKind(str(row[0])))
        )
        if coordinator is not None:
            await coordinator.process_claimed_capture(record)
            return True
        lease = record.lease
        if lease is None:
            raise RuntimeError("VISION-CAPTURE-WORK-LEASE")
        async with self._factory.unit_of_work() as unit:
            await unit.work.validate_lease(lease)
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations "
                "SET status='failed',error_code='VISION-SOURCE-UNAVAILABLE',"
                "settled_at=statement_timestamp() "
                "WHERE observation_id=%s AND status='capture_pending'",
                (observation_id,),
            )
            await unit.work.complete(
                lease, WorkResultRef("live_vision_observation", observation_id)
            )
        if self._failure_notification is not None and not self._stop.is_set():
            await self._failure_notification(
                observation_id, "VISION-SOURCE-UNAVAILABLE"
            )
        return True

    async def run(self) -> None:
        while not self._stop.is_set():
            if await self.process_once():
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    def stop(self) -> None:
        self._stop.set()


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
        return await _purge_frames(self._factory, self._catalog)

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.purge_once()
            async with self._factory.unit_of_work(read_only=True) as unit:
                row = await (
                    await unit.transaction.execute(
                        """SELECT min(frame.purge_after)
                           FROM armi.live_vision_observations observation,
                           jsonb_to_recordset(observation.frames) AS frame(artifact_id uuid,purge_after timestamptz)
                           WHERE frame.artifact_id IS NOT NULL"""
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


async def _purge_frames(
    factory: PostgreSQLRuntimeUnitOfWorkFactory, catalog: ArtifactCatalogPort
) -> int:
    # The observation owns its bounded frame list; retire references in the same transaction.
    count = 0
    async with factory.unit_of_work() as unit:
        rows = await (
            await unit.transaction.execute(
                """SELECT observation_id,frames,statement_timestamp()
               FROM armi.live_vision_observations observation
               WHERE EXISTS (
                   SELECT 1 FROM jsonb_to_recordset(observation.frames)
                   AS frame(artifact_id uuid,purge_after timestamptz)
                   WHERE frame.artifact_id IS NOT NULL AND frame.purge_after<=statement_timestamp())
               ORDER BY observation_id FOR UPDATE SKIP LOCKED"""
            )
        ).fetchall()
        for observation_id, frame_value, now in rows:
            frames = cast(list[_FrameDocument], frame_value)
            for frame in frames:
                if (
                    frame["artifact_id"] is not None
                    and datetime.fromisoformat(frame["purge_after"]) <= now
                ):
                    await catalog.retire_artifact(
                        unit, ArtifactId(UUID(frame["artifact_id"]))
                    )
                    frame["artifact_id"] = None
                    frame["purged_at"] = now.isoformat()
                    count += 1
            await unit.transaction.execute(
                "UPDATE armi.live_vision_observations SET frames=%s::jsonb WHERE observation_id=%s",
                (json.dumps(frames), observation_id),
            )
    return count


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _observation_from_row(row: Sequence[object]) -> VisualObservation:
    observation_id = UUID(str(row[0]))
    registered_at = row[5]
    if not isinstance(registered_at, datetime):
        raise RuntimeError("VISION-OBSERVATION-ROW")
    return VisualObservation(
        observation_id,
        VisualSourceKind(str(row[1])),
        ObservationOriginKind(str(row[2])),
        ObservationTrigger(str(row[3])),
        ObservationStatus(str(row[4])),
        registered_at,
        None if row[6] is None else float(str(row[6])),
        None if row[7] is None else str(row[7]),
        None if row[8] is None else str(row[8]),
    )


def _source_identity_document(source: VisualSourceIdentity) -> dict[str, object]:
    if isinstance(source, CameraSourceIdentity):
        return {
            "name": source.name,
            "device_path": source.device_path,
            "usb_location_id": source.usb_location_id,
            "backend": source.backend,
        }
    return {
        "source_device_name": source.source_device_name,
        "monitor_device_path": source.monitor_device_path,
        "edid_name": source.edid_name,
        "width": source.width,
        "height": source.height,
    }


__all__ = (
    "DurableVisualObservationCoordinator",
    "LiveVisionRetentionCoordinator",
    "VisualCaptureRouter",
)
