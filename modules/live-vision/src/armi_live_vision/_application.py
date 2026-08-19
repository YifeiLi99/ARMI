"""Durable private observation around the single visual-model call."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

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
from armi_kernel.application import ArtifactId, ArtifactPolicy, ArtifactPrivacyScope
from armi_kernel.contracts import Digest, Instant, TraceId
from armi_perception.api import (
    ExternalContentRecognitionStatus,
    PerceptionArtifactCatalogPort,
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
        catalog: PerceptionArtifactCatalogPort,
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
                    await self._catalog.mark_deleted(unit, ArtifactId(row[0]))
        return len(rows)

    async def observe(
        self,
        *,
        trigger: ObservationTrigger,
        frames: tuple[CameraFrame, ...],
        change_score: float | None,
    ) -> VisualObservation:
        await self.purge_expired_frames()
        if self._session_id is None:
            raise RuntimeError("live vision session is not open")
        observation_id, attempt_id = uuid7(), uuid7()
        self._number += 1
        trace_id = TraceId(uuid7().hex)
        registered_at = datetime.now(UTC)
        published_frames = [
            (
                frame,
                await self._publish(
                    frame.jpeg, "image/jpeg", "live.vision.selected-frame", trace_id
                ),
            )
            for frame in frames[:4]
        ]
        request_bytes = json.dumps(
            {
                "schema_version": "armi.visual-recognition-request.v1",
                "observation_id": str(observation_id),
                "trigger": trigger.value,
                "frame_digests": [
                    Digest.from_bytes(frame.jpeg).value for frame in frames[:4]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        published_request = await self._publish(
            request_bytes,
            "application/json",
            "live.vision.recognition-request",
            trace_id,
        )
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_vision_observations
                   (observation_id,session_id,subject_id,observation_no,trigger_kind,status,change_score)
                   VALUES (%s,%s,%s,%s,%s,'recognizing',%s)""",
                (
                    observation_id,
                    self._session_id,
                    self._subject_id,
                    self._number,
                    trigger.value,
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
        result = await self._recognizer.recognize_visual(
            VisualRecognitionRequest(
                observation_id,
                trigger.value,
                tuple(
                    VisualRecognitionInput(frame.jpeg, Instant(frame.captured_at))
                    for frame in frames[:4]
                ),
                self._previous_summary,
                trace_id,
            )
        )
        if result.status is not ExternalContentRecognitionStatus.SUCCEEDED:
            status = (
                ObservationStatus.UNKNOWN
                if result.status is ExternalContentRecognitionStatus.UNKNOWN
                else ObservationStatus.FAILED
            )
            await self._settle_failure(
                observation_id,
                attempt_id,
                status,
                result.error_code or "VISION-MODEL-FAILED",
            )
            return VisualObservation(
                observation_id,
                trigger,
                status,
                registered_at,
                change_score,
                error_code=result.error_code,
            )
        assert (
            result.raw_response is not None
            and result.scene_summary is not None
            and result.change_class is not None
        )
        published_response = await self._publish(
            result.raw_response,
            "application/json",
            "live.vision.recognition-response",
            trace_id,
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
                    visual_observation_id=observation_id,
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
                   evidence_id=%s,settled_at=statement_timestamp() WHERE observation_id=%s""",
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
                    observation_id,
                ),
            )
            if (
                trigger in {ObservationTrigger.INITIAL, ObservationTrigger.MANUAL}
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
        self._previous_summary = result.scene_summary
        return VisualObservation(
            observation_id,
            trigger,
            ObservationStatus.COMPLETED,
            registered_at,
            change_score,
            result.scene_summary,
        )

    async def _settle_failure(
        self,
        observation_id: UUID,
        attempt_id: UUID,
        status: ObservationStatus,
        code: str,
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


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


__all__ = ("DurableVisualObservationCoordinator",)
