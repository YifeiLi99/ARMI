"""PostgreSQL implementation of mood reads and writes."""

from __future__ import annotations

from uuid import UUID, uuid7

import rfc8785
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import MoodApplication
from .api import CandidateMoodDraft, MoodHead, MoodViolation

_INITIAL = rfc8785.dumps(
    {"schema_version": "armi.mood.v1", "emotions": [], "mood": None}
)


class PostgreSQLMoodOwner:
    __slots__ = ("_application",)

    def __init__(self, application: MoodApplication) -> None:
        self._application = application

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def current(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodHead:
        row = await (
            await transaction.execute(
                """SELECT head.current_revision_id, head.mood_version,
                          revision.semantic_payload
                   FROM armi.mood_heads AS head
                   JOIN armi.mood_revisions AS revision
                     ON revision.mood_revision_id=head.current_revision_id
                   WHERE head.subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise MoodViolation("MOOD-MISSING")
        return MoodHead(row[0], int(row[1]), rfc8785.dumps(row[2]))

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.mood_heads WHERE subject_id=%s",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(row[0])

    def _drafts(
        self, drafts: tuple[CandidateMoodDraft, ...]
    ) -> tuple[CandidateMoodDraft, ...]:
        return drafts

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool:
        selected = self._drafts(drafts)
        if len(selected) > 1:
            raise MoodViolation("MOOD-DRAFT-COUNT")
        if not selected:
            return True
        row = await (
            await transaction.execute(
                "SELECT mood_version FROM armi.mood_heads WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        return row is not None and int(row[0]) == selected[0].expected_version

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool:
        selected = self._drafts(drafts)
        if not selected:
            return False
        if len(selected) != 1:
            raise MoodViolation("MOOD-DRAFT-COUNT")
        draft = selected[0]
        head = await (
            await transaction.execute(
                "SELECT current_revision_id,mood_version FROM armi.mood_heads WHERE subject_id=%s",
                (subject_id,),
            )
        ).fetchone()
        if head is None or int(head[1]) != draft.expected_version:
            raise MoodViolation("MOOD-HEAD-STALE")
        revision_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.mood_revisions
               (mood_revision_id,subject_id,mood_version,previous_revision_id,
                origin_kind,origin_ref,subject_commit_id,proposal_ref,
                semantic_payload,privacy_scope)
               VALUES (%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb,'private')""",
            (
                revision_id,
                subject_id,
                draft.expected_version + 1,
                head[0],
                commit_id,
                commit_id,
                draft.proposal_ref,
                draft.canonical_next_state.decode("utf-8"),
            ),
        )
        updated = await (
            await transaction.execute(
                """UPDATE armi.mood_heads
                   SET current_revision_id=%s,mood_version=%s
                   WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s
                   RETURNING subject_id""",
                (
                    revision_id,
                    draft.expected_version + 1,
                    subject_id,
                    head[0],
                    draft.expected_version,
                ),
            )
        ).fetchone()
        if updated is None:
            raise MoodViolation("MOOD-HEAD-STALE")
        return True

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        revision_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.mood_revisions
               (mood_revision_id,subject_id,mood_version,origin_kind,origin_ref,
                semantic_payload,privacy_scope)
               VALUES (%s,%s,1,'bootstrap',%s,%s::jsonb,'private')""",
            (revision_id, subject_id, subject_id, _INITIAL.decode("utf-8")),
        )
        await transaction.execute(
            """INSERT INTO armi.mood_heads
               (subject_id,current_revision_id,mood_version) VALUES (%s,%s,1)""",
            (subject_id, revision_id),
        )


__all__ = ("PostgreSQLMoodOwner",)
