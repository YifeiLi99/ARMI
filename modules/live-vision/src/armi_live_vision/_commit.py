"""Register subject-requested capture work inside Subject Commit."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid7

from armi_kernel.application import (
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkType,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    ObservationOriginKind,
    VisualObservationCommitContext,
    VisualObservationRequestDraft,
)


class PostgreSQLVisualObservationCommit:
    async def commit_requests(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: VisualObservationCommitContext,
        commit_id: UUID,
        requests: tuple[VisualObservationRequestDraft, ...],
    ) -> None:
        del commit_id
        if not requests:
            return
        if len(requests) != 1:
            raise ValueError("VISION-SUBJECT-REQUEST-COUNT")
        request = requests[0]
        observation_id, work_id = uuid7(), WorkId(uuid7())
        payload = json.dumps(
            {
                "schema_version": "armi.visual-capture-request.v1",
                "source_kind": request.source_kind.value,
                "origin_kind": ObservationOriginKind.SUBJECT.value,
                "origin_episode_id": str(context.episode_id),
                "origin_scene_id": None
                if context.scene_id is None
                else str(context.scene_id),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = Digest.from_bytes(payload)
        now_row = await (
            await unit_of_work.transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if now_row is None:
            raise RuntimeError("VISION-DATABASE")
        await unit_of_work.work.enqueue(
            WorkDraft(
                work_id,
                WorkType.LIVE_VISION_CAPTURE,
                WorkOwner("live_vision_observation", observation_id),
                IdempotencyKey(f"vision-capture:{context.episode_id}"),
                digest,
                50,
                Instant(now_row[0]),
                Instant(now_row[0] + timedelta(minutes=10)),
                2,
                context.trace_id,
                SubjectId(context.subject_id),
                WorkPayloadRef("live_vision_observation", observation_id),
            )
        )
        await unit_of_work.transaction.execute(
            """INSERT INTO armi.live_vision_observations
               (observation_id,subject_id,source_kind,origin_kind,trigger_kind,
                origin_episode_id,origin_scene_id,origin_context_party_id,idempotency_key,request_digest,
                capture_work_id,status)
               VALUES (%s,%s,%s,'subject','subject_request',%s,%s,%s,%s,%s,%s,'capture_pending')""",
            (
                observation_id,
                context.subject_id,
                request.source_kind.value,
                context.episode_id,
                context.scene_id,
                context.creator_party_id,
                f"subject:{context.episode_id}",
                digest.value,
                work_id.value,
            ),
        )


__all__ = ("PostgreSQLVisualObservationCommit",)
