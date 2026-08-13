"""Durable recognition and finalization of external multimodal messages."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_evidence.api import EvidenceWritePort
from armi_interaction.api import (
    ExternalAccountKey,
    ExternalChannel,
    ExternalMessagePartKind,
    ExternalMessageViolation,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactViolation,
    PublishedArtifact,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Digest, TraceId
from armi_opportunity.api import OpportunityAdmissionPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._extractors import extract_external_content
from ._postgresql import (
    ExternalContentPartSnapshot,
    ExternalFinalizationPart,
    ExternalRecognitionSnapshot,
    PostgreSQLExternalContentRepository,
)
from .api import (
    ExternalContentRecognitionPort,
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionResult,
    ExternalContentRecognitionStatus,
    ExternalMediaFetchPort,
    PerceptionArtifactCatalogPort,
    PerceptionDurableWorkPort,
    PerceptionWakeupPort,
)

_RECOGNIZE_WORK = "external.content.recognize"
_FINALIZE_WORK = "external.content.finalize"
EXTERNAL_CONTENT = "external.content"
OPPORTUNITY_AVAILABLE = "opportunity.available"
_MAX_BYTES = {
    ExternalMessagePartKind.IMAGE: 10 * 1024 * 1024,
    ExternalMessagePartKind.AUDIO: 25 * 1024 * 1024,
    ExternalMessagePartKind.VIDEO: 45 * 1024 * 1024,
    ExternalMessagePartKind.FILE: 45 * 1024 * 1024,
}
_MAX_LOCAL_FILE_BYTES = 25 * 1024 * 1024
_MAX_PROJECTION_BYTES = 256 * 1024
Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class ExternalContentPipeline:
    __slots__ = (
        "_catalog",
        "_diagnostic",
        "_factory",
        "_fetch",
        "_lease_owner",
        "_recognizer",
        "_repository",
        "_stop",
        "_storage",
        "_target_for",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        catalog: PerceptionArtifactCatalogPort,
        work: PerceptionDurableWorkPort,
        evidence: EvidenceWritePort,
        opportunity: OpportunityAdmissionPort,
        fetch: ExternalMediaFetchPort,
        recognizer: ExternalContentRecognitionPort,
        target_for: Callable[[ExternalMessagePartKind], tuple[str, str]],
        wakeups: PerceptionWakeupPort,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._fetch = fetch
        self._recognizer = recognizer
        self._target_for = target_for
        self._wakeups = wakeups
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._catalog = catalog
        self._repository = PostgreSQLExternalContentRepository(evidence, opportunity)
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()

    async def open(self) -> None:
        try:
            await self._storage.prepare()
            async with self._factory.unit_of_work() as unit:
                recovered = await self._repository.recover_terminal_recognition(unit)
            if recovered:
                self._wakeups.notify(EXTERNAL_CONTENT)
        except ArtifactViolation, RuntimeTransactionFailure, WorkViolation:
            raise ExternalMessageViolation(
                "EXTERNAL-MESSAGE-RECOGNITION-UNAVAILABLE"
            ) from None

    async def close(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    async def execute_once(self) -> bool:
        for work_kind in (_RECOGNIZE_WORK, _FINALIZE_WORK):
            try:
                records = await self._work.claim(
                    work_kind=work_kind,
                    lease_owner=self._lease_owner,
                    lease_seconds=600,
                    limit=1,
                )
            except WorkViolation:
                raise ExternalMessageViolation(
                    "DB-EXTERNAL-MESSAGE-UNAVAILABLE"
                ) from None
            if not records:
                continue
            lease = cast(WorkLease, records[0].lease)
            if work_kind == _RECOGNIZE_WORK:
                await self._recognize(lease)
            else:
                await self._finalize(lease)
            return True
        return False

    async def _recognize(self, lease: WorkLease) -> None:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit:
                snapshot = await self._repository.recognition_snapshot(unit, lease)
            for part in snapshot.parts:
                if part.status != "pending":
                    continue
                await self._recognize_part(lease, snapshot, part)
            async with self._factory.unit_of_work() as unit:
                await self._repository.finish_recognition(
                    unit, lease=lease, snapshot=snapshot
                )
            self._wakeups.notify(EXTERNAL_CONTENT)
        except ExternalMessageViolation as error:
            if error.code != "EXTERNAL-MESSAGE-WORK-STALE":
                self._diagnostic("external.content.recognition.failed")
                await self._fail_work(lease, error.code)
        except RuntimeTransactionFailure, WorkViolation:
            self._diagnostic("external.content.recognition.transient_failure")
            await self._terminalize_recognition(lease)

    async def _recognize_part(
        self,
        lease: WorkLease,
        snapshot: ExternalRecognitionSnapshot,
        part: ExternalContentPartSnapshot,
    ) -> None:
        attempt_id: UUID | None = None
        try:
            if (
                part.declared_byte_size is not None
                and part.declared_byte_size > _MAX_BYTES[part.kind]
            ):
                raise ExternalMessageViolation("EXTERNAL-MESSAGE-MEDIA-TOO-LARGE")
            downloaded = await self._fetch.fetch(
                channel=ExternalChannel(snapshot.channel),
                account_key=ExternalAccountKey(snapshot.account_key),
                kind=part.kind,
                locator=part.locator,
                max_bytes=_download_limit(part),
            )
            extracted = extract_external_content(
                kind=part.kind,
                content=downloaded.content,
                file_name=downloaded.file_name,
                visual_role=part.visual_role,
                source_summary=part.source_summary,
            )
            if (
                part.kind is ExternalMessagePartKind.FILE
                and not extracted.requires_provider
                and len(downloaded.content) > _MAX_LOCAL_FILE_BYTES
            ):
                raise ExternalMessageViolation("EXTERNAL-MESSAGE-MEDIA-TOO-LARGE")
            raw = await self._publish(
                downloaded.content,
                media_type=extracted.media_type,
                logical_kind=f"external.message.{part.kind.value}.raw",
                trace_id=snapshot.trace_id,
                creator_visible=snapshot.purpose == "creator_message",
            )
            async with self._factory.unit_of_work() as unit:
                raw_registration = await self._catalog.register(
                    unit, ArtifactId(uuid7()), raw
                )
                await self._repository.attach_raw(
                    unit,
                    part_id=part.part_id,
                    raw_artifact_id=raw_registration.ref.artifact_id.value,
                )
                if part.kind is ExternalMessagePartKind.IMAGE:
                    assert (
                        extracted.pixel_width is not None
                        and extracted.pixel_height is not None
                        and extracted.frame_count is not None
                    )
                    await self._repository.attach_visual_detection(
                        unit,
                        part_id=part.part_id,
                        media_type=extracted.media_type,
                        pixel_width=extracted.pixel_width,
                        pixel_height=extracted.pixel_height,
                        frame_count=extracted.frame_count,
                    )
            if not extracted.requires_provider:
                assert extracted.text is not None
                interpretation = await self._publish_text(
                    extracted.text,
                    trace_id=snapshot.trace_id,
                    creator_visible=snapshot.purpose == "creator_message",
                )
                async with self._factory.unit_of_work() as unit:
                    interpretation_registration = await self._catalog.register(
                        unit, ArtifactId(uuid7()), interpretation
                    )
                    await self._repository.settle_success(
                        unit,
                        part_id=part.part_id,
                        raw_artifact_id=raw_registration.ref.artifact_id.value,
                        interpretation_artifact_id=interpretation_registration.ref.artifact_id.value,
                        interpretation_text=extracted.text,
                    )
                return
            provider, model_id = self._target_for(part.kind)
            request_evidence = await self._publish(
                json.dumps(
                    {
                        "schema_version": "armi.external-content-recognition-request.v2",
                        "provider": provider,
                        "model_id": model_id,
                        "part_kind": part.kind.value,
                        "file_name": downloaded.file_name,
                        "media_type": extracted.media_type,
                        "raw_artifact_id": str(raw_registration.ref.artifact_id.value),
                        "raw_content_digest": raw_registration.ref.content_digest.value,
                        "visual_role": (
                            None if part.visual_role is None else part.visual_role.value
                        ),
                        "source_kind": part.source_kind,
                        "source_summary": part.source_summary,
                        "pixel_width": extracted.pixel_width,
                        "pixel_height": extracted.pixel_height,
                        "frame_count": extracted.frame_count,
                        "visual_inputs": [
                            {
                                "ordinal": index,
                                "media_type": item.media_type,
                                "content_digest": Digest.from_bytes(item.content).value,
                            }
                            for index, item in enumerate(
                                extracted.visual_inputs, start=1
                            )
                        ],
                        "visual_conversion": (
                            "armi.image-visual-input.v1"
                            if part.kind is ExternalMessagePartKind.IMAGE
                            else None
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                media_type="application/json",
                logical_kind="external.message.recognition.request",
                trace_id=snapshot.trace_id,
                creator_visible=False,
            )
            async with self._factory.unit_of_work() as unit:
                request_registration = await self._catalog.register(
                    unit, ArtifactId(uuid7()), request_evidence
                )
                attempt_id = await self._repository.begin_attempt(
                    unit,
                    lease=lease,
                    part_id=part.part_id,
                    raw_artifact_id=raw_registration.ref.artifact_id.value,
                    request_artifact_id=request_registration.ref.artifact_id.value,
                    provider=provider,
                    model_id=model_id,
                )
            result = await self._recognizer.recognize(
                ExternalContentRecognitionRequest(
                    kind=part.kind,
                    content=downloaded.content,
                    file_name=downloaded.file_name,
                    media_type=extracted.media_type,
                    trace_id=snapshot.trace_id,
                    visual_role=part.visual_role,
                    source_kind=part.source_kind,
                    source_summary=part.source_summary,
                    visual_inputs=extracted.visual_inputs,
                )
            )
            if result.status is ExternalContentRecognitionStatus.SUCCEEDED:
                assert result.text is not None and result.raw_response is not None
                interpretation = await self._publish_text(
                    result.text,
                    trace_id=snapshot.trace_id,
                    creator_visible=snapshot.purpose == "creator_message",
                )
                response = await self._publish(
                    result.raw_response,
                    media_type="application/json",
                    logical_kind="external.message.recognition.response",
                    trace_id=snapshot.trace_id,
                    creator_visible=False,
                )
                async with self._factory.unit_of_work() as unit:
                    interpretation_registration = await self._catalog.register(
                        unit, ArtifactId(uuid7()), interpretation
                    )
                    response_registration = await self._catalog.register(
                        unit, ArtifactId(uuid7()), response
                    )
                    await self._repository.settle_success(
                        unit,
                        part_id=part.part_id,
                        raw_artifact_id=raw_registration.ref.artifact_id.value,
                        interpretation_artifact_id=interpretation_registration.ref.artifact_id.value,
                        interpretation_text=result.text,
                        attempt_id=attempt_id,
                        response_artifact_id=response_registration.ref.artifact_id.value,
                        result=result,
                    )
            else:
                await self._settle_failure(
                    part.part_id,
                    "unknown"
                    if result.status is ExternalContentRecognitionStatus.UNKNOWN
                    else "failed",
                    result.error_code or "EXTERNAL-MESSAGE-RECOGNITION",
                    attempt_id=attempt_id,
                    result=result,
                )
        except ExternalMessageViolation as error:
            await self._settle_failure(
                part.part_id, "failed", error.code, attempt_id=attempt_id
            )
        except ArtifactViolation, OSError:
            await self._settle_failure(
                part.part_id,
                "failed",
                "EXTERNAL-MESSAGE-ARTIFACT",
                attempt_id=attempt_id,
            )

    async def _settle_failure(
        self,
        part_id: UUID,
        status: str,
        code: str,
        *,
        attempt_id: UUID | None = None,
        result: ExternalContentRecognitionResult | None = None,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            await self._repository.settle_failure(
                unit,
                part_id=part_id,
                status=status,
                error_code=code,
                attempt_id=attempt_id,
                result=result,
            )

    async def _finalize(self, lease: WorkLease) -> None:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit:
                snapshot = await self._repository.finalization_snapshot(unit, lease)
            if snapshot.existing_evidence_id is not None:
                async with self._factory.unit_of_work() as unit:
                    await self._repository.finalize(
                        unit,
                        lease=lease,
                        snapshot=snapshot,
                    )
                return
            projection = _render_projection(snapshot.parts)
            published = await self._publish_text(
                projection,
                trace_id=snapshot.trace_id,
                creator_visible=snapshot.purpose == "creator_message",
                logical_kind=(
                    "creator.input.text"
                    if snapshot.purpose == "creator_message"
                    else "other_human.input.text"
                ),
            )
            async with self._factory.unit_of_work() as unit:
                registration = await self._catalog.register(
                    unit, ArtifactId(uuid7()), published
                )
                await self._repository.finalize(
                    unit,
                    lease=lease,
                    snapshot=snapshot,
                    artifact_id=registration.ref.artifact_id.value,
                    content_digest=registration.ref.content_digest,
                )
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
        except ExternalMessageViolation as error:
            if error.code != "EXTERNAL-MESSAGE-WORK-STALE":
                await self._fail_work(lease, error.code)
        except WorkViolation:
            self._diagnostic("external.content.finalization.stale")
        except ArtifactViolation, RuntimeTransactionFailure, OSError:
            self._diagnostic("external.content.finalization.failed")
            try:
                async with self._factory.unit_of_work() as unit:
                    requeued = await self._repository.requeue_finalization(unit, lease)
                if requeued:
                    self._wakeups.notify(EXTERNAL_CONTENT)
            except RuntimeTransactionFailure:
                self._diagnostic("external.content.finalization.settlement_deferred")

    async def _fail_work(self, lease: WorkLease, code: str) -> None:
        try:
            await self._work.fail(lease, error_code=code)
        except WorkViolation:
            self._diagnostic("external.content.settlement.deferred")

    async def _terminalize_recognition(self, lease: WorkLease) -> None:
        await self._fail_work(lease, "EXTERNAL-CONTENT-RECOGNITION")
        try:
            async with self._factory.unit_of_work() as unit:
                recovered = await self._repository.recover_terminal_recognition(unit)
            if recovered:
                self._wakeups.notify(EXTERNAL_CONTENT)
        except RuntimeTransactionFailure, WorkViolation:
            self._diagnostic("external.content.recognition.settlement_deferred")

    async def _publish_text(
        self,
        value: str,
        *,
        trace_id: TraceId,
        creator_visible: bool,
        logical_kind: str = "external.message.interpretation",
    ) -> PublishedArtifact:
        return await self._publish(
            value.encode("utf-8"),
            media_type="text/plain",
            logical_kind=logical_kind,
            trace_id=trace_id,
            creator_visible=creator_visible,
        )

    async def _publish(
        self,
        value: bytes,
        *,
        media_type: str,
        logical_kind: str,
        trace_id: TraceId,
        creator_visible: bool,
    ) -> PublishedArtifact:
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                media_type,
                logical_kind,
                "external.content",
                trace_id,
                ArtifactPrivacyScope.CREATOR_VISIBLE
                if creator_visible
                else ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)

    async def run_worker(self) -> None:
        observed = self._wakeups.version(EXTERNAL_CONTENT)
        while not self._stop.is_set():
            try:
                worked = await self.execute_once()
            except ExternalMessageViolation:
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                EXTERNAL_CONTENT,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )


def _render_projection(parts: tuple[ExternalFinalizationPart, ...]) -> str:
    values: list[str] = []
    for part in parts:
        if part.kind is ExternalMessagePartKind.TEXT:
            values.append(part.text_value or "")
        elif part.kind is ExternalMessagePartKind.MENTION:
            values.append(
                "@全体成员" if part.target_key == "all" else f"@QQ({part.target_key})"
            )
        elif part.kind is ExternalMessagePartKind.REPLY:
            values.append(f"[回复消息 {part.target_key}]")
        elif part.kind is ExternalMessagePartKind.FACE:
            values.append(f"[QQ表情 {part.text_value}]")
        elif part.kind is ExternalMessagePartKind.UNKNOWN:
            values.append(f"[不支持的消息类型: {part.text_value}]")
        elif part.kind is ExternalMessagePartKind.IMAGE:
            values.append(_render_image_projection(part))
        elif part.status == "succeeded":
            values.append(
                f"[{_part_label(part.kind)}识别结果]\n{part.interpretation_text}"
            )
        else:
            values.append(f"[{_part_label(part.kind)}无法读取,状态: {part.status}]")
    encoded = "".join(values).encode("utf-8")
    if len(encoded) <= _MAX_PROJECTION_BYTES:
        return encoded.decode("utf-8")
    marker = "\n[内容已按 ARMI 单条认知材料上限截断]".encode()
    clipped = encoded[: _MAX_PROJECTION_BYTES - len(marker)]
    while True:
        try:
            return clipped.decode("utf-8") + marker.decode("utf-8")
        except UnicodeDecodeError:
            clipped = clipped[:-1]


def _part_label(kind: ExternalMessagePartKind) -> str:
    return {
        ExternalMessagePartKind.IMAGE: "图片",
        ExternalMessagePartKind.AUDIO: "语音",
        ExternalMessagePartKind.VIDEO: "视频",
        ExternalMessagePartKind.FILE: "文件",
    }[kind]


def _render_image_projection(part: ExternalFinalizationPart) -> str:
    metadata: list[str] = []
    if part.visual_role:
        metadata.append(f"ARMI视觉角色: {part.visual_role.value}")
    if part.source_kind:
        metadata.append(f"QQ来源类别: {part.source_kind}")
    if part.source_summary:
        metadata.append(f"QQ摘要: {part.source_summary}")
    if (
        part.detected_media_type
        and part.pixel_width is not None
        and part.pixel_height is not None
        and part.frame_count is not None
    ):
        metadata.append(
            f"本地检测: {part.detected_media_type}, "
            f"{part.pixel_width}x{part.pixel_height}, {part.frame_count}帧"
        )
    prefix = "[图片来源信息]\n" + "\n".join(metadata) if metadata else "[图片]"
    if part.status == "succeeded":
        interpretation_kind = (
            "本地内容解释"
            if (part.interpretation_text or "").startswith("QQ 提供的商城表情摘要: ")
            else "外部视觉观察"
        )
        return f"{prefix}\n[{interpretation_kind}]\n{part.interpretation_text}"
    return f"{prefix}\n[原图无法读取,状态: {part.status}]"


def _download_limit(part: ExternalContentPartSnapshot) -> int:
    if part.kind is not ExternalMessagePartKind.FILE:
        return _MAX_BYTES[part.kind]
    suffix = Path(part.file_name or "").suffix.lower()
    return _MAX_BYTES[part.kind] if suffix == ".pdf" else _MAX_LOCAL_FILE_BYTES


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


__all__ = ("ExternalContentPipeline",)
