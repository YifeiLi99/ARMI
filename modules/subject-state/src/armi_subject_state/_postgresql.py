"""PostgreSQL implementation of subject-state reads and writes."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

import psycopg
import rfc8785
from armi_kernel.application import CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import SubjectStateApplication
from .api import (
    LifeModeHead,
    SubjectComponentSummary,
    SubjectStateHead,
    SubjectStateKind,
    SubjectStateLifeRecordItem,
    SubjectStateViolation,
    SubjectSummary,
)

_INITIAL: dict[SubjectStateKind, dict[str, object]] = {
    SubjectStateKind.SELF: {
        "schema_version": "armi.self.v1",
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
    SubjectStateKind.MIND: {
        "schema_version": "armi.mind.v2",
        "understanding": [],
        "attention": [],
        "thoughts": [],
        "wishes": [],
        "motivations": [],
    },
    SubjectStateKind.LIFE_MODE: {
        "schema_version": "armi.life-mode.v1",
        "mode": "awake",
        "active_activities": [],
    },
}


def probe_subject_state_counts(conninfo: str) -> tuple[int, int]:
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            row = connection.execute(
                "SELECT (SELECT count(*) FROM armi.subject_component_heads), "
                "(SELECT count(*) FROM armi.subject_component_revisions)"
            ).fetchone()
    except psycopg.Error:
        return (-1, -1)
    return (-1, -1) if row is None else (int(row[0]), int(row[1]))


class PostgreSQLSubjectStateOwner:
    __slots__ = ("_application",)

    def __init__(self, application: SubjectStateApplication) -> None:
        self._application = application

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
            SELECT head.component_kind, revision.component_revision_id,
                   head.component_version, revision.semantic_payload
            FROM armi.subject_component_heads AS head
            JOIN armi.subject_component_revisions AS revision
              ON revision.component_revision_id = head.current_revision_id
            WHERE head.subject_id = %s
            ORDER BY CASE head.component_kind WHEN 'self' THEN 1 WHEN 'mind' THEN 2 WHEN 'life_mode' THEN 3 END
        """,
                (subject_id,),
            )
        ).fetchall()
        if tuple(str(row[0]) for row in rows) != ("self", "mind", "life_mode"):
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
            SELECT head.current_revision_id, head.component_version, revision.semantic_payload
            FROM armi.subject_component_heads AS head
            JOIN armi.subject_component_revisions AS revision ON revision.component_revision_id = head.current_revision_id
            WHERE head.subject_id = %s AND head.component_kind = 'life_mode'
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
              AND (%s::text IS NULL OR semantic_payload::text ILIKE '%%' || %s || '%%')
              AND (%s::timestamptz IS NULL OR (created_at, 'self_change'::text, component_revision_id) < (%s, %s, %s))
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

    async def creator_summary(
        self, transaction: PostgreSQLTransaction, *, creator_party_id: UUID
    ) -> SubjectSummary:
        rows = await (
            await transaction.execute(
                """
            SELECT subject.subject_version, head.component_kind, head.component_version,
                   commit.subject_commit_id, statement_timestamp()
            FROM armi.subjects AS subject
            JOIN armi.parties AS creator ON creator.party_id = %s AND creator.party_kind = 'creator'
              AND creator.creator_role = 'unique_primary_creator' AND creator.status = 'active'
            JOIN armi.subject_component_heads AS head ON head.subject_id = subject.subject_id
            LEFT JOIN LATERAL (SELECT subject_commit_id FROM armi.subject_commits WHERE subject_id = subject.subject_id ORDER BY new_subject_version DESC LIMIT 1) AS commit ON true
            WHERE subject.singleton_key = 1 AND subject.status = 'active'
            ORDER BY CASE head.component_kind WHEN 'self' THEN 1 WHEN 'mind' THEN 2 ELSE 3 END
        """,
                (creator_party_id,),
            )
        ).fetchall()
        if len(rows) != 3:
            raise SubjectStateViolation("SUBJECT-STATE-SUMMARY")
        schema = {
            SubjectStateKind.SELF: "armi.self.v1",
            SubjectStateKind.MIND: "armi.mind.v2",
            SubjectStateKind.LIFE_MODE: "armi.life-mode.v1",
        }
        kinds = tuple(SubjectStateKind(str(row[1])) for row in rows)
        return SubjectSummary(
            int(rows[0][0]),
            tuple(
                SubjectComponentSummary(kind, int(row[2]), schema[kind])
                for row, kind in zip(rows, kinds, strict=True)
            ),
            rows[0][3],
            rows[0][4],
        )

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.subject_component_heads WHERE subject_id = %s AND component_kind IN ('self','mind','life_mode')",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(row[0])

    def _drafts(self, drafts: tuple[CandidateOwnerDraft, ...]):
        return tuple(
            self._application.decode(item.canonical_payload)
            for item in drafts
            if item.owner in {item.value for item in SubjectStateKind}
        )

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool:
        for draft in sorted(self._drafts(drafts), key=lambda item: item.kind.value):
            row = await (
                await transaction.execute(
                    "SELECT component_version FROM armi.subject_component_heads WHERE subject_id = %s AND component_kind = %s FOR UPDATE",
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
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> tuple[SubjectStateKind, ...]:
        changed: list[SubjectStateKind] = []
        for draft in sorted(self._drafts(drafts), key=lambda item: item.kind.value):
            head = await (
                await transaction.execute(
                    "SELECT current_revision_id, component_version FROM armi.subject_component_heads WHERE subject_id = %s AND component_kind = %s",
                    (subject_id, draft.kind.value),
                )
            ).fetchone()
            if head is None or int(head[1]) != draft.expected_version:
                raise SubjectStateViolation("SUBJECT-STATE-HEAD-STALE")
            revision_id = uuid7()
            await transaction.execute(
                """INSERT INTO armi.subject_component_revisions (component_revision_id, subject_id, component_kind, component_version, previous_revision_id, origin_kind, origin_ref, subject_commit_id, proposal_ref, semantic_payload, privacy_scope) VALUES (%s,%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb,'private')""",
                (
                    revision_id,
                    subject_id,
                    draft.kind.value,
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
                    "UPDATE armi.subject_component_heads SET current_revision_id=%s, component_version=%s WHERE subject_id=%s AND component_kind=%s AND current_revision_id=%s AND component_version=%s RETURNING subject_id",
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
                """SELECT head.current_revision_id, head.component_version, revision.semantic_payload FROM armi.subject_component_heads AS head JOIN armi.subject_component_revisions AS revision ON revision.component_revision_id=head.current_revision_id WHERE head.subject_id=%s AND head.component_kind='life_mode' FOR UPDATE OF head""",
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
            """INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,component_kind,component_version,previous_revision_id,origin_kind,origin_ref,subject_commit_id,proposal_ref,semantic_payload,privacy_scope) VALUES (%s,%s,'life_mode',%s,%s,'subject_commit',%s,%s,%s,%s::jsonb,'private')""",
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
                "UPDATE armi.subject_component_heads SET current_revision_id=%s, component_version=component_version+1 WHERE subject_id=%s AND component_kind='life_mode' AND current_revision_id=%s AND component_version=%s RETURNING subject_id",
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
                """INSERT INTO armi.subject_component_revisions (component_revision_id,subject_id,component_kind,component_version,origin_kind,origin_ref,semantic_payload,privacy_scope) VALUES (%s,%s,%s,1,'bootstrap',%s,%s::jsonb,'private')""",
                (
                    revision_id,
                    subject_id,
                    kind.value,
                    subject_id,
                    json.dumps(_INITIAL[kind], sort_keys=True, separators=(",", ":")),
                ),
            )
            await transaction.execute(
                "INSERT INTO armi.subject_component_heads (subject_id,component_kind,current_revision_id,component_version) VALUES (%s,%s,%s,1)",
                (subject_id, kind.value, revision_id),
            )


__all__ = ("PostgreSQLSubjectStateOwner", "probe_subject_state_counts")
