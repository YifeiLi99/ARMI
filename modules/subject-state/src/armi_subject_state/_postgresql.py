"""PostgreSQL implementation of subject-state reads and writes."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._application import SubjectStateApplication
from .api import (
    CandidateSubjectStateDraft,
    LifeModeHead,
    SubjectStateBirthContinuity,
    SubjectStateHead,
    SubjectStateKind,
    SubjectStateLifeRecordItem,
    SubjectStateViolation,
)

_INITIAL: dict[SubjectStateKind, dict[str, object]] = {
    SubjectStateKind.SELF: {
        "schema_kind": "armi.self",
        "identity_kind": "electronic_person",
        "creator_role_awareness": "unique_primary_creator",
        "name": None,
        "self_description": None,
        "interests": [],
        "values": [],
        "preferences": [],
        "goals": [],
        "self_narrative": None,
        "tensions": [],
    },
    SubjectStateKind.LIFE_MODE: {
        "schema_kind": "armi.life-mode",
        "mode": "awake",
        "active_activities": [],
    },
}


class PostgreSQLSubjectStateOwner:
    __slots__ = ("_application",)

    def __init__(self, application: SubjectStateApplication) -> None:
        self._application = application

    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> SubjectStateBirthContinuity:
        if subject_id is None:
            row = transaction.execute(
                """SELECT (SELECT count(*) FROM armi.subject_component_revisions WHERE is_current ),(SELECT count(*) FROM armi.subject_component_revisions)"""
            ).fetchone()
        else:
            row = transaction.execute(
                """SELECT (SELECT count(*) FROM armi.subject_component_revisions WHERE is_current AND subject_id=%s),(SELECT count(*) FROM armi.subject_component_revisions WHERE subject_id=%s)""",
                (subject_id, subject_id),
            ).fetchone()
        if row is None:
            raise SubjectStateViolation("SUBJECT-STATE-CONTINUITY")
        return SubjectStateBirthContinuity(
            int(cast(int, row[0])), int(cast(int, row[1]))
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def active_activity_ids(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]:
        return (
            await self.life_mode(transaction, subject_id=subject_id)
        ).active_activity_ids

    async def current_heads(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[SubjectStateHead, ...]:
        rows = await (
            await transaction.execute(
                """
            SELECT head.component_kind, head.component_revision_id,
                   head.component_version, head.semantic_payload
            FROM armi.subject_component_revisions AS head WHERE head.is_current AND head.subject_id = %s
            ORDER BY CASE head.component_kind WHEN 'self' THEN 1 WHEN 'life_mode' THEN 2 END
        """,
                (subject_id,),
            )
        ).fetchall()
        if tuple(str(row[0]) for row in rows) != ("self", "life_mode"):
            raise SubjectStateViolation("SUBJECT-STATE-MISSING")
        return tuple(
            SubjectStateHead(
                SubjectStateKind(str(row[0])),
                row[1],
                int(row[2]),
                rfc8785.dumps(row[3]),
            )
            for row in rows
        )

    async def life_mode(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> LifeModeHead:
        row = await (
            await transaction.execute(
                """
            SELECT head.component_revision_id, head.component_version, head.semantic_payload
            FROM armi.subject_component_revisions AS head WHERE head.is_current AND head.subject_id = %s AND head.component_kind = 'life_mode'
        """,
                (subject_id,),
            )
        ).fetchone()
        if row is None or type(row[2]) is not dict:
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE")
        active = cast(dict[str, object], row[2]).get("active_activities")
        try:
            ids = tuple(UUID(str(item)) for item in cast(list[object], active))
        except TypeError, ValueError:
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE") from None
        if (
            type(active) is not list
            or len(ids) > 1
            or any(item.version != 7 for item in ids)
        ):
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE")
        return LifeModeHead(row[0], int(row[1]), ids)

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[Any, str, UUID] | None,
        limit: int,
    ) -> tuple[SubjectStateLifeRecordItem, ...]:
        rows = await (
            await transaction.execute(
                """
            SELECT component_revision_id, left(semantic_payload::text, 4096), origin_kind, created_at
            FROM armi.subject_component_revisions
            WHERE subject_id = %s AND component_kind = 'self'
              AND (%s::text IS NULL OR semantic_payload::text ILIKE '%%' || %s::text || '%%')
              AND (%s::timestamptz IS NULL OR
                   (created_at, 'self_change'::text, component_revision_id)
                       < (%s::timestamptz, %s::text, %s::uuid))
            ORDER BY created_at DESC, component_revision_id DESC LIMIT %s
        """,
                (
                    subject_id,
                    query_text,
                    query_text,
                    None if before is None else before[0],
                    None if before is None else before[0],
                    None if before is None else before[1],
                    None if before is None else before[2],
                    limit,
                ),
            )
        ).fetchall()
        return tuple(
            SubjectStateLifeRecordItem(row[0], str(row[1]), str(row[2]), row[3])
            for row in rows
        )

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.subject_component_revisions WHERE is_current AND subject_id = %s AND component_kind IN ('self','life_mode')""",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(row[0])

    def _drafts(
        self, drafts: tuple[CandidateSubjectStateDraft, ...]
    ) -> tuple[CandidateSubjectStateDraft, ...]:
        return drafts

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateSubjectStateDraft, ...],
    ) -> bool:
        for draft in sorted(self._drafts(drafts), key=lambda item: item.kind.value):
            row = await (
                await transaction.execute(
                    """SELECT component_version FROM armi.subject_component_revisions WHERE is_current AND subject_id = %s AND component_kind = %s FOR UPDATE""",
                    (subject_id, draft.kind.value),
                )
            ).fetchone()
            if row is None or int(row[0]) != draft.expected_version:
                return False
        return True

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateSubjectStateDraft, ...],
    ) -> tuple[SubjectStateKind, ...]:
        changed: list[SubjectStateKind] = []
        for draft in sorted(self._drafts(drafts), key=lambda item: item.kind.value):
            head = await (
                await transaction.execute(
                    """SELECT component_revision_id, component_version FROM armi.subject_component_revisions WHERE is_current AND subject_id = %s AND component_kind = %s""",
                    (subject_id, draft.kind.value),
                )
            ).fetchone()
            if head is None or int(head[1]) != draft.expected_version:
                raise SubjectStateViolation("SUBJECT-STATE-HEAD-STALE")
            next_payload = json.loads(draft.canonical_next_state)
            revision_id = uuid7()
            await transaction.execute(
                """INSERT INTO armi.subject_component_revisions (component_revision_id, subject_id, component_kind, component_version, previous_revision_id, origin_kind, origin_ref, subject_commit_id, proposal_ref, semantic_payload) VALUES (%s,%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb)""",
                (
                    revision_id,
                    subject_id,
                    draft.kind.value,
                    draft.expected_version + 1,
                    head[0],
                    commit_id,
                    commit_id,
                    draft.proposal_ref,
                    rfc8785.dumps(next_payload).decode("utf-8"),
                ),
            )
            updated = await (
                await transaction.execute(
                    """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::text AS component_kind, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.component_revision_id
                    FROM armi.subject_component_revisions AS candidate, input
                    WHERE candidate.component_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.component_version=input.new_version AND NOT candidate.is_current AND candidate.component_kind=input.component_kind
                ), retired AS (
                    UPDATE armi.subject_component_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.component_revision_id=input.old_id
                      AND previous.component_version=input.old_version AND previous.is_current AND previous.component_kind=input.component_kind
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.subject_component_revisions AS current SET is_current=true
                FROM target, retired WHERE current.component_revision_id=target.component_revision_id RETURNING current.subject_id""",
                    (
                        revision_id,
                        draft.expected_version + 1,
                        subject_id,
                        draft.kind.value,
                        head[0],
                        draft.expected_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise SubjectStateViolation("SUBJECT-STATE-HEAD-STALE")
            changed.append(draft.kind)
        return tuple(changed)

    async def update_life_focus(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        activity_id: UUID | None,
        proposal_ref: str,
    ) -> None:
        head = await (
            await transaction.execute(
                """SELECT head.component_revision_id, head.component_version, head.semantic_payload FROM armi.subject_component_revisions AS head WHERE head.is_current AND head.subject_id=%s AND head.component_kind='life_mode' FOR UPDATE OF head""",
                (subject_id,),
            )
        ).fetchone()
        if head is None or type(head[2]) is not dict:
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE")
        payload = cast(dict[str, object], head[2]).copy()
        active = payload.get("active_activities")
        if type(active) is not list or len(cast(list[object], active)) > 1:
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE")
        payload["active_activities"] = [] if activity_id is None else [str(activity_id)]
        revision_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,component_kind,component_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload) VALUES (%s,%s,'life_mode',%s,%s,'subject_commit',%s,%s,%s,%s::jsonb)""",
            (
                revision_id,
                subject_id,
                int(head[1]) + 1,
                head[0],
                commit_id,
                commit_id,
                proposal_ref,
                rfc8785.dumps(cast(Any, payload)).decode(),
            ),
        )
        updated = await (
            await transaction.execute(
                """WITH input AS (SELECT %s::uuid AS new_id, %s::uuid AS subject_id, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.component_revision_id
                    FROM armi.subject_component_revisions AS candidate, input
                    WHERE candidate.component_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.component_version=input.old_version+1 AND NOT candidate.is_current AND candidate.component_kind='life_mode'
                ), retired AS (
                    UPDATE armi.subject_component_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.component_revision_id=input.old_id
                      AND previous.component_version=input.old_version AND previous.is_current AND previous.component_kind='life_mode'
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.subject_component_revisions AS current SET is_current=true
                FROM target, retired WHERE current.component_revision_id=target.component_revision_id RETURNING current.subject_id""",
                (revision_id, subject_id, head[0], int(head[1])),
            )
        ).fetchone()
        if updated is None:
            raise SubjectStateViolation("SUBJECT-STATE-LIFE-MODE-STALE")

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        for kind in SubjectStateKind:
            revision_id = uuid7()
            await transaction.execute(
                """INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,component_kind,component_version,origin_kind,origin_ref,semantic_payload) VALUES (%s,%s,%s,1,'bootstrap',%s,%s::jsonb)""",
                (
                    revision_id,
                    subject_id,
                    kind.value,
                    subject_id,
                    json.dumps(_INITIAL[kind], sort_keys=True, separators=(",", ":")),
                ),
            )
            await transaction.execute(
                """UPDATE armi.subject_component_revisions SET is_current=true WHERE subject_id=%s AND component_kind=%s AND component_revision_id=%s AND component_version=1 AND NOT is_current""",
                (subject_id, kind.value, revision_id),
            )


__all__ = ("PostgreSQLSubjectStateOwner",)
