"""Mind-owned durable state; the caller owns the Subject Commit transaction."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from .api import (
    CandidateMindDraft,
    MindBirthContinuity,
    MindHead,
    MindRevision,
    MindViolation,
    initial_mind_state,
    mind_attention_projection,
    mind_motivation_projection,
    mind_signals,
    prepare_mind_change,
)


class PostgreSQLMindOwner:
    async def motivation_status(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        as_of: datetime,
        consumed: frozenset[tuple[str, str, str]],
    ) -> list[dict[str, object]]:
        head = await self.current_head(transaction, subject_id=subject_id)
        return mind_motivation_projection(
            head.canonical_state, as_of=as_of, consumed=consumed
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def current_head(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MindHead:
        row = await (
            await transaction.execute(
                "SELECT h.current_revision_id,h.mind_version,r.semantic_payload FROM armi.mind_heads h "
                "JOIN armi.mind_revisions r ON r.mind_revision_id=h.current_revision_id WHERE h.subject_id=%s",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise MindViolation("MIND-MISSING")
        return MindHead(row[0], int(cast(int, row[1])), rfc8785.dumps(row[2]))

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.mind_heads WHERE subject_id=%s",
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
    ) -> tuple[MindRevision, ...]:
        if not 1 <= limit <= 200 or (before_version is not None and before_version < 1):
            raise MindViolation("MIND-HISTORY-RANGE")
        rows = await (
            await transaction.execute(
                """SELECT mind_revision_id,mind_version,previous_revision_id,
                      origin_kind,origin_ref,subject_commit_id,admin_change_id,
                      created_at,data_rights_redacted_at,semantic_payload
               FROM armi.mind_revisions WHERE subject_id=%s
                 AND (%s::bigint IS NULL OR mind_version<%s)
               ORDER BY mind_version DESC LIMIT %s""",
                (subject_id, before_version, before_version, limit),
            )
        ).fetchall()
        return tuple(
            MindRevision(
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
                 SELECT 1 FROM armi.mind_heads h JOIN armi.mind_revisions r
                   ON r.mind_revision_id=h.current_revision_id AND r.subject_id=h.subject_id
                 WHERE h.subject_id=%s AND h.mind_version=r.mind_version
               ) AND NOT EXISTS (
                 SELECT 1 FROM armi.mind_revisions r
                 LEFT JOIN armi.mind_revisions p ON p.mind_revision_id=r.previous_revision_id
                 WHERE r.subject_id=%s AND (
                   (r.mind_version=1 AND r.previous_revision_id IS NOT NULL)
                   OR (r.mind_version>1 AND (p.mind_revision_id IS NULL
                     OR p.subject_id<>r.subject_id OR p.mind_version>=r.mind_version))
                 )
               ) AND (
                 SELECT count(*)=max(mind_version)
                 FROM armi.mind_revisions WHERE subject_id=%s
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
        return mind_attention_projection(
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
        return mind_signals(
            head.canonical_state,
            event_purpose=event_purpose,
            event_ref=event_ref,
            event_at=event_at,
            activity_id=activity_id,
        )

    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> MindBirthContinuity:
        row = transaction.execute(
            "SELECT (SELECT count(*) FROM armi.mind_heads WHERE %s::uuid IS NULL OR subject_id=%s),"
            "(SELECT count(*) FROM armi.mind_revisions WHERE %s::uuid IS NULL OR subject_id=%s)",
            (subject_id, subject_id, subject_id, subject_id),
        ).fetchone()
        if row is None:
            raise MindViolation("MIND-CONTINUITY")
        return MindBirthContinuity(int(cast(int, row[0])), int(cast(int, row[1])))

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMindDraft, ...],
    ) -> bool:
        if len(drafts) > 1:
            raise MindViolation("MIND-DUPLICATE-CANDIDATE")
        if not drafts:
            return True
        row = await (
            await transaction.execute(
                "SELECT mind_version FROM armi.mind_heads WHERE subject_id=%s FOR UPDATE",
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
        drafts: tuple[CandidateMindDraft, ...],
    ) -> None:
        if len(drafts) > 1:
            raise MindViolation("MIND-DUPLICATE-CANDIDATE")
        for draft in drafts:
            head = await self.current_head(transaction, subject_id=subject_id)
            clock = await (
                await transaction.execute("SELECT statement_timestamp()")
            ).fetchone()
            if clock is None:
                raise MindViolation("MIND-CLOCK")
            payload = prepare_mind_change(
                head, draft, now=clock[0], commit_id=commit_id
            )
            revision_id = uuid7()
            await transaction.execute(
                "INSERT INTO armi.mind_revisions (mind_revision_id,subject_id,mind_version,previous_revision_id,"
                "origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload,privacy_scope) "
                "VALUES (%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb,'private')",
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
                "UPDATE armi.mind_heads SET current_revision_id=%s,mind_version=%s "
                "WHERE subject_id=%s AND current_revision_id=%s AND mind_version=%s",
                (
                    revision_id,
                    head.version + 1,
                    subject_id,
                    head.current_revision_id,
                    head.version,
                ),
            )
            if result.rowcount != 1:
                raise MindViolation("MIND-HEAD-STALE")

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        revision_id = uuid7()
        await transaction.execute(
            "INSERT INTO armi.mind_revisions (mind_revision_id,subject_id,mind_version,origin_kind,origin_ref,semantic_payload,privacy_scope) "
            "VALUES (%s,%s,1,'bootstrap',%s,%s::jsonb,'private')",
            (revision_id, subject_id, subject_id, initial_mind_state().decode()),
        )
        await transaction.execute(
            "INSERT INTO armi.mind_heads (subject_id,current_revision_id,mind_version) VALUES (%s,%s,1)",
            (subject_id, revision_id),
        )


__all__ = ("PostgreSQLMindOwner",)
