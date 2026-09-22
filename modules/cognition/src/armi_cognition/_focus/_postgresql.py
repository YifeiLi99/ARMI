"""Focus-owned durable state; the caller owns the Subject Commit transaction."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from .api import (
    CandidateFocusDraft,
    FocusBirthContinuity,
    FocusHead,
    FocusRevision,
    FocusViolation,
    focus_attention_projection,
    focus_signals,
    initial_focus_state,
    prepare_focus_change,
)


class PostgreSQLFocusOwner:
    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def current_head(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> FocusHead:
        row = await (
            await transaction.execute(
                """SELECT h.focus_revision_id,h.focus_version,h.semantic_payload FROM armi.focus_revisions AS h WHERE h.is_current AND h.subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise FocusViolation("FOCUS-MISSING")
        return FocusHead(row[0], int(cast(int, row[1])), rfc8785.dumps(row[2]))

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.focus_revisions WHERE is_current AND subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))

    async def history(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        before_version: int | None = None,
        limit: int = 50,
    ) -> tuple[FocusRevision, ...]:
        if not 1 <= limit <= 200 or (before_version is not None and before_version < 1):
            raise FocusViolation("FOCUS-HISTORY-RANGE")
        rows = await (
            await transaction.execute(
                """SELECT focus_revision_id,focus_version,previous_revision_id,
                      origin_kind,origin_ref,subject_commit_id,admin_change_id,
                      created_at,data_rights_redacted_at,semantic_payload
               FROM armi.focus_revisions WHERE subject_id=%s
                 AND (%s::bigint IS NULL OR focus_version<%s)
               ORDER BY focus_version DESC LIMIT %s""",
                (subject_id, before_version, before_version, limit),
            )
        ).fetchall()
        return tuple(
            FocusRevision(
                row[0],
                int(row[1]),
                row[2],
                str(row[3]),
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                rfc8785.dumps(row[9]),
            )
            for row in rows
        )

    async def history_is_continuous(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """SELECT EXISTS (
                 SELECT 1 FROM armi.focus_revisions AS h
                 WHERE h.is_current AND h.subject_id=%s
               ) AND NOT EXISTS (
                 SELECT 1 FROM armi.focus_revisions r
                 LEFT JOIN armi.focus_revisions p ON p.focus_revision_id=r.previous_revision_id
                 WHERE r.subject_id=%s AND (
                   (r.focus_version=1 AND r.previous_revision_id IS NOT NULL)
                   OR (r.focus_version>1 AND (p.focus_revision_id IS NULL
                     OR p.subject_id<>r.subject_id OR p.focus_version>=r.focus_version))
                 )
               ) AND (
                 SELECT count(*)=max(focus_version)
                 FROM armi.focus_revisions WHERE subject_id=%s
               )""",
                (subject_id, subject_id, subject_id),
            )
        ).fetchone()
        return row is not None and row[0] is True

    async def attention_status(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        as_of: datetime,
        consumed: frozenset[tuple[str, str, str]],
    ) -> list[dict[str, object]]:
        head = await self.current_head(transaction, subject_id=subject_id)
        return focus_attention_projection(
            head.canonical_state, as_of=as_of, consumed=consumed
        )

    async def consideration_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        event_purpose: str | None = None,
        event_ref: UUID | None = None,
        event_at: datetime | None = None,
        activity_id: UUID | None = None,
    ) -> tuple[ConsiderationSignal, ...]:
        head = await self.current_head(transaction, subject_id=subject_id)
        return focus_signals(
            head.canonical_state,
            event_purpose=event_purpose,
            event_ref=event_ref,
            event_at=event_at,
            activity_id=activity_id,
        )

    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> FocusBirthContinuity:
        row = transaction.execute(
            """SELECT (SELECT count(*) FROM armi.focus_revisions WHERE is_current AND (%s::uuid IS NULL OR subject_id=%s)),(SELECT count(*) FROM armi.focus_revisions WHERE (%s::uuid IS NULL OR subject_id=%s))""",
            (subject_id, subject_id, subject_id, subject_id),
        ).fetchone()
        if row is None:
            raise FocusViolation("FOCUS-CONTINUITY")
        return FocusBirthContinuity(int(cast(int, row[0])), int(cast(int, row[1])))

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateFocusDraft, ...],
    ) -> bool:
        if len(drafts) > 1:
            raise FocusViolation("FOCUS-DUPLICATE-CANDIDATE")
        if not drafts:
            return True
        row = await (
            await transaction.execute(
                """SELECT focus_version FROM armi.focus_revisions WHERE is_current AND subject_id=%s FOR UPDATE""",
                (subject_id,),
            )
        ).fetchone()
        return row is not None and int(cast(int, row[0])) == drafts[0].expected_version

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateFocusDraft, ...],
    ) -> None:
        if len(drafts) > 1:
            raise FocusViolation("FOCUS-DUPLICATE-CANDIDATE")
        for draft in drafts:
            head = await self.current_head(transaction, subject_id=subject_id)
            clock = await (
                await transaction.execute("SELECT statement_timestamp()")
            ).fetchone()
            if clock is None:
                raise FocusViolation("FOCUS-CLOCK")
            payload = prepare_focus_change(
                head, draft, now=clock[0], commit_id=commit_id
            )
            revision_id = uuid7()
            await transaction.execute(
                "INSERT INTO armi.focus_revisions (focus_revision_id,subject_id,focus_version,previous_revision_id,"
                "origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload) "
                "VALUES (%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb)",
                (
                    revision_id,
                    subject_id,
                    head.version + 1,
                    head.current_revision_id,
                    commit_id,
                    commit_id,
                    draft.proposal_ref,
                    payload.decode(),
                ),
            )
            result = await transaction.execute(
                """WITH input AS (SELECT %s::uuid AS new_id, %s::bigint AS new_version, %s::uuid AS subject_id, %s::uuid AS old_id, %s::bigint AS old_version),
                target AS (
                    SELECT candidate.focus_revision_id
                    FROM armi.focus_revisions AS candidate, input
                    WHERE candidate.focus_revision_id=input.new_id AND candidate.subject_id=input.subject_id
                      AND candidate.focus_version=input.new_version AND NOT candidate.is_current
                ), retired AS (
                    UPDATE armi.focus_revisions AS previous SET is_current=false FROM input
                    WHERE previous.subject_id=input.subject_id AND previous.focus_revision_id=input.old_id
                      AND previous.focus_version=input.old_version AND previous.is_current
                      AND EXISTS (SELECT 1 FROM target)
                    RETURNING previous.subject_id
                )
                UPDATE armi.focus_revisions AS current SET is_current=true
                FROM target, retired WHERE current.focus_revision_id=target.focus_revision_id""",
                (
                    revision_id,
                    head.version + 1,
                    subject_id,
                    head.current_revision_id,
                    head.version,
                ),
            )
            if result.rowcount != 1:
                raise FocusViolation("FOCUS-HEAD-STALE")

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        revision_id = uuid7()
        await transaction.execute(
            "INSERT INTO armi.focus_revisions (focus_revision_id,subject_id,focus_version,origin_kind,origin_ref,semantic_payload) "
            "VALUES (%s,%s,1,'bootstrap',%s,%s::jsonb)",
            (revision_id, subject_id, subject_id, initial_focus_state().decode()),
        )
        await transaction.execute(
            """UPDATE armi.focus_revisions SET is_current=true WHERE subject_id=%s AND focus_revision_id=%s AND focus_version=1 AND NOT is_current""",
            (subject_id, revision_id),
        )


__all__ = ("PostgreSQLFocusOwner",)
