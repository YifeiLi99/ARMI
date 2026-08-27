"""PostgreSQL implementation owned by the relationship module."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_data_rights.api import DataRightsVisibilityPort
from armi_kernel.contracts import OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorStale,
    RuntimeTransactionFailure,
)

from ._codec import (
    boundary_to_dict,
    commitment_to_dict,
    decode_boundaries,
    decode_commitments,
    decode_event,
    decode_facts,
    decode_issues,
    decode_resolution,
    event_to_dict,
    fact_to_dict,
    issue_to_dict,
    resolution_to_dict,
)
from .api import (
    RELATIONSHIP_PROJECTION_VERSION,
    CandidateRelationshipDraft,
    CreatorRelationshipItem,
    CreatorRelationshipRevision,
    CreatorRelationshipTimeline,
    RelationshipContextBundle,
    RelationshipSnapshot,
    RelationshipStatus,
    RelationshipViolation,
)


class PostgreSQLRelationshipOwner:
    __slots__ = (
        "_creator_party_id",
        "_cursor",
        "_factory",
        "_subject_id",
        "_visibility",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
        environment_id: UUID,
        cursor_key: bytes,
        visibility: DataRightsVisibilityPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._cursor = ProjectionCursorCodec(
            cursor_key, environment_id, creator_party_id
        )
        self._factory = factory
        self._subject_id = subject_id
        self._visibility = visibility

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def current(self) -> CreatorRelationshipItem | None:
        async with self._read_connection() as connection:
            subject_id = self._subject_id
            rows = await (
                await connection.execute(
                    """
                    SELECT relationship.relationship_id,
                           relationship.current_revision_id,
                           relationship.head_version,
                           relationship.created_at,
                           revision.relationship_revision_id,
                           revision.revision_no,
                           revision.facts,
                           revision.interpretation,
                           revision.boundaries,
                           revision.commitments,
                           revision.open_issues,
                           revision.commitment_event,
                           revision.issue_resolution,
                           revision.relationship_status,
                           revision.created_at
                    FROM armi.relationships AS relationship
                    JOIN armi.relationship_revisions AS revision
                      ON revision.relationship_revision_id = relationship.current_revision_id
                    WHERE relationship.subject_id = %s
                      AND relationship.other_party_id = %s
                      AND relationship.scope = 'creator_social'
                      AND relationship.tombstoned_at IS NULL
                    LIMIT 2
                    """,
                    (subject_id, self._creator_party_id),
                )
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise RelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
        row = rows[0]
        return CreatorRelationshipItem(
            row[0], row[1], int(row[2]), _revision(row[4:]), row[3]
        )

    async def timeline(
        self, relationship_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> CreatorRelationshipTimeline:
        ceiling: int | None = None
        before: int | None = None
        if cursor is not None:
            try:
                page = self._cursor.decode(
                    cursor,
                    projection_version=RELATIONSHIP_PROJECTION_VERSION,
                    resource_kind="relationship-timeline",
                    resource_ref=str(relationship_id),
                    page_limit=limit,
                    query={},
                )
                ceiling = cast(int, page.snapshot_ceiling.get("revision_no"))
                before = cast(int, page.boundary.get("before_revision_no"))
            except ProjectionCursorStale:
                raise RelationshipViolation("RELATIONSHIP-CURSOR-STALE") from None
            except TypeError, ValueError, ProjectionCursorInvalid:
                raise RelationshipViolation("RELATIONSHIP-CURSOR") from None
            if (
                type(ceiling) is not int
                or ceiling < 1
                or type(before) is not int
                or before < 1
            ):
                raise RelationshipViolation("RELATIONSHIP-CURSOR")
        async with self._read_connection() as connection:
            subject_id = self._subject_id
            visible = await (
                await connection.execute(
                    """
                    SELECT 1 FROM armi.relationships
                    WHERE relationship_id = %s AND subject_id = %s
                      AND other_party_id = %s AND scope = 'creator_social'
                      AND tombstoned_at IS NULL
                    """,
                    (relationship_id, subject_id, self._creator_party_id),
                )
            ).fetchone()
            if visible is None:
                raise RelationshipViolation("RELATIONSHIP-QUERY-NOT-FOUND")
            if ceiling is None:
                ceiling_row = await (
                    await connection.execute(
                        """SELECT max(revision_no) FROM armi.relationship_revisions
                           WHERE relationship_id=%s""",
                        (relationship_id,),
                    )
                ).fetchone()
                if ceiling_row is None or ceiling_row[0] is None:
                    raise RelationshipViolation("RELATIONSHIP-QUERY-NOT-FOUND")
                ceiling = int(ceiling_row[0])
            rows = await (
                await connection.execute(
                    """
                    SELECT relationship_revision_id, revision_no, facts,
                           interpretation, boundaries, commitments, open_issues,
                           commitment_event, issue_resolution, relationship_status,
                           created_at
                    FROM armi.relationship_revisions
                    WHERE relationship_id = %s AND privacy_scope = 'private'
                      AND revision_no<=%s
                      AND (%s::bigint IS NULL OR revision_no<%s)
                    ORDER BY revision_no DESC LIMIT %s
                    """,
                    (relationship_id, ceiling, before, before, limit + 1),
                )
            ).fetchall()
        page_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page_rows:
            next_cursor = self._cursor.encode(
                projection_version=RELATIONSHIP_PROJECTION_VERSION,
                resource_kind="relationship-timeline",
                resource_ref=str(relationship_id),
                page_limit=limit,
                query={},
                snapshot_ceiling={"revision_no": ceiling},
                boundary={"before_revision_no": int(page_rows[-1][1])},
            )
        return CreatorRelationshipTimeline(
            relationship_id, tuple(_revision(row) for row in page_rows), next_cursor
        )

    async def context_sources(self, party_id: UUID) -> tuple[object, ...]:
        snapshot = await self._snapshot_for_party(party_id)
        if snapshot is None:
            return ()
        return (
            *snapshot.facts,
            *snapshot.boundaries,
            *snapshot.commitments,
            *snapshot.open_issues,
        )

    async def candidate_snapshot(self, party_id: UUID) -> object | None:
        return await self._snapshot_for_party(party_id)

    async def current_for_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        other_party_id: UUID,
        scope: str,
        expected_head_version: int | None = None,
    ) -> RelationshipSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT relationship.relationship_id,
                       relationship.current_revision_id,
                       relationship.head_version,
                       relationship.subject_party_id,
                       relationship.other_party_id,
                       relationship.scope,
                       revision.relationship_revision_id,
                       revision.revision_no,
                       revision.facts,
                       revision.interpretation,
                       revision.boundaries,
                       revision.commitments,
                       revision.open_issues,
                       revision.commitment_event,
                       revision.issue_resolution,
                       revision.relationship_status,
                       revision.created_at
                FROM armi.relationships AS relationship
                JOIN armi.relationship_revisions AS revision
                  ON revision.relationship_revision_id = relationship.current_revision_id
                WHERE relationship.subject_id = %s
                  AND relationship.life_generation_id = %s
                  AND relationship.other_party_id = %s
                  AND relationship.scope = %s
                  AND relationship.tombstoned_at IS NULL
                  AND (%s::bigint IS NULL OR relationship.head_version = %s::bigint)
                LIMIT 2
                """,
                (
                    subject_id,
                    generation_id,
                    other_party_id,
                    scope,
                    expected_head_version,
                    expected_head_version,
                ),
            )
        ).fetchall()
        if not row:
            return None
        if len(row) != 1:
            raise RelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
        item = row[0]
        return RelationshipSnapshot(
            item[0],
            item[1],
            int(item[2]),
            item[3],
            item[4],
            str(item[5]),
            _revision(item[6:]),
        )

    async def all_current(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
    ) -> tuple[RelationshipSnapshot, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT relationship.relationship_id,
                       relationship.current_revision_id,
                       relationship.head_version,
                       relationship.subject_party_id,
                       relationship.other_party_id,
                       relationship.scope,
                       revision.relationship_revision_id,
                       revision.revision_no,
                       revision.facts,
                       revision.interpretation,
                       revision.boundaries,
                       revision.commitments,
                       revision.open_issues,
                       revision.commitment_event,
                       revision.issue_resolution,
                       revision.relationship_status,
                       revision.created_at
                FROM armi.relationships AS relationship
                JOIN armi.relationship_revisions AS revision
                  ON revision.relationship_revision_id = relationship.current_revision_id
                WHERE relationship.subject_id = %s
                  AND relationship.life_generation_id = %s
                  AND relationship.tombstoned_at IS NULL
                ORDER BY relationship.relationship_id
                """,
                (subject_id, generation_id),
            )
        ).fetchall()
        return tuple(
            RelationshipSnapshot(
                item[0],
                item[1],
                int(item[2]),
                item[3],
                item[4],
                str(item[5]),
                _revision(item[6:]),
            )
            for item in rows
        )

    async def context_bundle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        other_party_id: UUID | None,
        scope: str | None,
    ) -> RelationshipContextBundle:
        snapshots = (
            await self.all_current(
                transaction,
                subject_id=subject_id,
                generation_id=generation_id,
            )
            if other_party_id is None or scope is None
            else tuple(
                item
                for item in (
                    await self.current_for_party(
                        transaction,
                        subject_id=subject_id,
                        generation_id=generation_id,
                        other_party_id=other_party_id,
                        scope=scope,
                    ),
                )
                if item is not None
            )
        )
        relationships = tuple(
            (
                snapshot.relationship_id,
                snapshot.head_version,
                rfc8785.dumps(
                    cast(
                        Any,
                        {
                            "scope": snapshot.scope,
                            "facts": [
                                fact_to_dict(value) for value in snapshot.revision.facts
                            ],
                            "interpretation": snapshot.revision.interpretation,
                            "boundaries": [
                                boundary_to_dict(value)
                                for value in snapshot.revision.boundaries
                            ],
                            "status": snapshot.revision.status.value,
                        },
                    )
                ),
            )
            for snapshot in snapshots
        )
        commitments = tuple(
            (
                commitment.commitment_id,
                snapshot.head_version,
                rfc8785.dumps(
                    cast(
                        Any,
                        {
                            key: value
                            for key, value in commitment_to_dict(commitment).items()
                            if key != "commitment_id"
                        },
                    )
                ),
                commitment.status.value,
            )
            for snapshot in snapshots
            for commitment in snapshot.revision.commitments
        )
        issues = tuple(
            (
                issue.issue_id,
                snapshot.head_version,
                rfc8785.dumps(
                    {
                        "kind": issue.kind.value,
                        "summary": issue.summary,
                        "status": issue.status.value,
                    }
                ),
            )
            for snapshot in snapshots
            for issue in snapshot.revision.open_issues
        )
        return RelationshipContextBundle(relationships, commitments, issues)

    async def life_record_branch(self, party_id: UUID) -> tuple[object, ...]:
        snapshot = await self._snapshot_for_party(party_id)
        return () if snapshot is None else (snapshot,)

    async def outreach_basis(self, party_id: UUID) -> object | None:
        return await self._snapshot_for_party(party_id)

    async def _snapshot_for_party(
        self, party_id: UUID
    ) -> CreatorRelationshipRevision | None:
        async with self._read_connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT revision.relationship_revision_id, revision.revision_no,
                           revision.facts, revision.interpretation,
                           revision.boundaries, revision.commitments,
                           revision.open_issues, revision.commitment_event,
                           revision.issue_resolution, revision.relationship_status,
                           revision.created_at
                    FROM armi.relationships AS relationship
                    JOIN armi.relationship_revisions AS revision
                      ON revision.relationship_revision_id = relationship.current_revision_id
                    WHERE relationship.other_party_id = %s
                      AND relationship.tombstoned_at IS NULL
                    LIMIT 2
                    """,
                    (party_id,),
                )
            ).fetchall()
        if not row:
            return None
        if len(row) != 1:
            raise RelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
        return _revision(row[0])

    @asynccontextmanager
    async def _read_connection(self) -> AsyncGenerator[PostgreSQLTransaction]:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                yield unit_of_work.transaction
        except RuntimeTransactionFailure:
            raise RelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE") from None

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        validation_id: UUID,
        experience_ids: dict[str, UUID],
        drafts: tuple[CandidateRelationshipDraft, ...],
    ) -> tuple[UUID, ...]:
        affected: list[UUID] = []
        for relationship in drafts:
            await _commit_one(
                transaction,
                subject_id=subject_id,
                generation_id=generation_id,
                commit_id=commit_id,
                validation_id=validation_id,
                experience_ids=experience_ids,
                relationship=relationship,
                visibility=self._visibility,
            )
            affected.append(relationship.relationship_id)
        return tuple(affected)

    async def affected_relationship_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT relationship_id FROM armi.relationship_revisions
                WHERE candidate_validation_id = %s ORDER BY relationship_id
                """,
                (validation_id,),
            )
        ).fetchall()
        return tuple(row[0] for row in rows)


async def _commit_one(
    connection: PostgreSQLTransaction,
    *,
    subject_id: UUID,
    generation_id: UUID,
    commit_id: UUID,
    validation_id: UUID,
    experience_ids: dict[str, UUID],
    relationship: CandidateRelationshipDraft,
    visibility: DataRightsVisibilityPort,
) -> None:
    source_experience_id = experience_ids.get(relationship.source_experience_ref)
    if source_experience_id is None:
        raise RelationshipViolation("RELATIONSHIP-COMMIT-VALIDATION")
    revision_id = uuid7()
    previous = None
    revision_no = 1
    if relationship.current_revision_id is None:
        existing = await (
            await connection.execute(
                """
                SELECT relationship_id FROM armi.relationships
                WHERE subject_id = %s AND other_party_id = %s AND scope = %s
                FOR UPDATE
                """,
                (subject_id, relationship.other_party_id, relationship.scope),
            )
        ).fetchone()
        if existing is not None:
            raise RelationshipViolation("RELATIONSHIP-COMMIT-HEAD-STALE")
        await connection.execute(
            """
            INSERT INTO armi.relationships (
                relationship_id, subject_id, life_generation_id,
                subject_party_id, other_party_id, scope,
                current_revision_id, head_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (
                relationship.relationship_id,
                subject_id,
                generation_id,
                relationship.subject_party_id,
                relationship.other_party_id,
                relationship.scope,
                revision_id,
            ),
        )
    else:
        row = await (
            await connection.execute(
                """
                SELECT relationship.current_revision_id, relationship.head_version,
                       revision.revision_no, revision.relationship_status,
                       relationship.tombstoned_at, revision.interpretation,
                       revision.boundaries, revision.open_issues,
                       revision.facts, revision.commitments
                FROM armi.relationships AS relationship
                JOIN armi.relationship_revisions AS revision
                  ON revision.relationship_revision_id = relationship.current_revision_id
                WHERE relationship.relationship_id = %s
                  AND relationship.subject_id = %s
                  AND relationship.life_generation_id = %s
                FOR UPDATE OF relationship
                """,
                (relationship.relationship_id, subject_id, generation_id),
            )
        ).fetchone()
        if (
            row is None
            or row[0] != relationship.current_revision_id
            or int(row[1]) != relationship.expected_head_version
            or row[4] is not None
            or (str(row[3]) == "ended" and not relationship.reopen)
        ):
            raise RelationshipViolation("RELATIONSHIP-COMMIT-HEAD-STALE")
        was_ended = str(row[3]) == "ended"
        if relationship.reopen != was_ended:
            raise RelationshipViolation("RELATIONSHIP-REOPEN")
        current_boundaries = decode_boundaries(row[6])
        current_issues = decode_issues(row[7])
        if relationship.reopen:
            restrictions = await visibility.party_restrictions(
                connection, relationship.other_party_id
            )
            reused_experience = await (
                await connection.execute(
                    """
                    SELECT 1 FROM armi.relationship_experience_links
                    WHERE experience_id = %s LIMIT 1
                    """,
                    (source_experience_id,),
                )
            ).fetchone()
            if (
                bool(restrictions & {"stop_contact", "stop_use", "delete_related"})
                or reused_experience is not None
                or relationship.interpretation == str(row[5])
                or any(item.kind.value == "exit" for item in relationship.boundaries)
                or not any(item.kind.value == "exit" for item in current_boundaries)
            ):
                raise RelationshipViolation("RELATIONSHIP-REOPEN")
        if relationship.issue_resolution is not None:
            target = relationship.issue_resolution.issue_id
            if not any(item.issue_id == target for item in current_issues) or any(
                item.issue_id == target for item in relationship.open_issues
            ):
                raise RelationshipViolation("RELATIONSHIP-ISSUE-RESOLUTION")
        if (
            decode_facts(row[8]) == relationship.facts
            and str(row[5]) == relationship.interpretation
            and current_boundaries == relationship.boundaries
            and decode_commitments(row[9]) == relationship.commitments
            and current_issues == relationship.open_issues
            and relationship.commitment_event is None
            and relationship.issue_resolution is None
        ):
            raise RelationshipViolation("RELATIONSHIP-NO-CHANGE")
        previous = relationship.current_revision_id
        revision_no = int(row[2]) + 1

    await connection.execute(
        """
        INSERT INTO armi.relationship_revisions (
            relationship_revision_id, relationship_id, revision_no,
            previous_revision_id, subject_commit_id, candidate_validation_id,
            proposal_ref, facts, interpretation, boundaries, commitments,
            open_issues, commitment_event, issue_resolution,
            relationship_status, mechanism_identity, privacy_scope
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, 'private')
        """,
        (
            revision_id,
            relationship.relationship_id,
            revision_no,
            previous,
            commit_id,
            validation_id,
            relationship.proposal_ref,
            json.dumps(
                [fact_to_dict(v) for v in relationship.facts], ensure_ascii=False
            ),
            relationship.interpretation,
            json.dumps(
                [boundary_to_dict(v) for v in relationship.boundaries],
                ensure_ascii=False,
            ),
            json.dumps(
                [commitment_to_dict(v) for v in relationship.commitments],
                ensure_ascii=False,
            ),
            json.dumps(
                [issue_to_dict(v) for v in relationship.open_issues], ensure_ascii=False
            ),
            None
            if relationship.commitment_event is None
            else json.dumps(
                event_to_dict(relationship.commitment_event), ensure_ascii=False
            ),
            None
            if relationship.issue_resolution is None
            else json.dumps(
                resolution_to_dict(relationship.issue_resolution), ensure_ascii=False
            ),
            relationship.status.value,
            relationship.mechanism_identity,
        ),
    )
    if previous is not None:
        updated = await (
            await connection.execute(
                """
                UPDATE armi.relationships
                SET current_revision_id = %s, head_version = head_version + 1
                WHERE relationship_id = %s AND current_revision_id = %s
                  AND head_version = %s RETURNING relationship_id
                """,
                (
                    revision_id,
                    relationship.relationship_id,
                    previous,
                    relationship.expected_head_version,
                ),
            )
        ).fetchone()
        if updated is None:
            raise RelationshipViolation("RELATIONSHIP-COMMIT-HEAD-STALE")
    await connection.execute(
        """
        INSERT INTO armi.relationship_experience_links (
            relationship_revision_id, experience_id, link_kind, ordinal
        ) VALUES (%s, %s, %s, 1)
        """,
        (
            revision_id,
            source_experience_id,
            "supports_commitment_event"
            if relationship.commitment_event is not None
            else "supports_relationship_change",
        ),
    )


def _revision(row: tuple[Any, ...]) -> CreatorRelationshipRevision:
    try:
        return CreatorRelationshipRevision(
            relationship_revision_id=row[0],
            revision_no=int(row[1]),
            facts=decode_facts(row[2]),
            interpretation=str(row[3]),
            boundaries=decode_boundaries(row[4]),
            commitments=decode_commitments(row[5]),
            open_issues=decode_issues(row[6]),
            commitment_event=decode_event(row[7]),
            issue_resolution=decode_resolution(row[8]),
            status=RelationshipStatus(str(row[9])),
            occurred_at=row[10],
        )
    except IndexError, TypeError, ValueError, RelationshipViolation:
        raise RelationshipViolation("RELATIONSHIP-QUERY-SHAPE") from None


__all__ = ("PostgreSQLRelationshipOwner",)
