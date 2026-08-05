"""PostgreSQL-backed Creator relationship projection."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import psycopg
from armi_kernel.application import (
    CandidateViolation,
    CreatorRelationshipItem,
    CreatorRelationshipRevision,
    CreatorRelationshipTimeline,
    CreatorRelationshipViolation,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipCommitment,
    RelationshipCommitmentEvent,
    RelationshipCommitmentEventKind,
    RelationshipCommitmentStatus,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipIssue,
    RelationshipIssueKind,
    RelationshipIssueStatus,
    RelationshipPartyRole,
    RelationshipStatus,
)
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .role_policy import physical_role_name

_SEARCH_PATH = "pg_catalog, armi"
_PAGE_SIZE = 100


async def _configure(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLCreatorRelationshipQuery:
    """Read only the primary Creator's structured relationship revisions."""

    __slots__ = (
        "_creator_party_id",
        "_expected_role",
        "_pool",
        "_pool_timeout_seconds",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        pool_timeout_seconds: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout_seconds = pool_timeout_seconds

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise CreatorRelationshipViolation(
                    "RELATIONSHIP-QUERY-UNAVAILABLE"
                )

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-creator-relationship-query",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except (psycopg.Error, PoolTimeout):
            raise CreatorRelationshipViolation(
                "RELATIONSHIP-QUERY-UNAVAILABLE"
            ) from None

    async def close(self) -> None:
        await self._pool.close()

    async def current(self) -> CreatorRelationshipItem | None:
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id = await self._scope(connection)
                rows = await (
                    await connection.execute(
                        """
                        SELECT relationship.relationship_id,
                               relationship.current_revision_id,
                               relationship.head_version,
                               relationship.created_at,
                               revision.relationship_revision_id,
                               revision.revision_no, revision.facts,
                               revision.interpretation, revision.boundaries,
                               revision.commitments, revision.open_issues,
                               revision.commitment_event,
                               revision.relationship_status,
                               revision.created_at
                        FROM armi.relationships AS relationship
                        JOIN armi.relationship_revisions AS revision
                          ON revision.relationship_revision_id =
                             relationship.current_revision_id
                         AND revision.relationship_id = relationship.relationship_id
                        WHERE relationship.subject_id = %s
                          AND relationship.other_party_id = %s
                          AND relationship.scope = 'creator_social'
                          AND revision.privacy_scope = 'private'
                        LIMIT 2
                        """,
                        (subject_id, self._creator_party_id),
                    )
                ).fetchall()
        except CreatorRelationshipViolation:
            raise
        except (psycopg.Error, PoolTimeout):
            raise CreatorRelationshipViolation(
                "RELATIONSHIP-QUERY-UNAVAILABLE"
            ) from None
        if not rows:
            return None
        if len(rows) != 1:
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE")
        row = rows[0]
        return CreatorRelationshipItem(
            relationship_id=row[0],
            current_revision_id=row[1],
            head_version=row[2],
            created_at=row[3],
            current=_revision(row[4:]),
        )

    async def timeline(self, relationship_id: UUID) -> CreatorRelationshipTimeline:
        if type(relationship_id) is not UUID or relationship_id.version != 7:
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-ID")
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id = await self._scope(connection)
                visible = await (
                    await connection.execute(
                        """
                        SELECT 1
                        FROM armi.relationships
                        WHERE relationship_id = %s AND subject_id = %s
                          AND other_party_id = %s AND scope = 'creator_social'
                        """,
                        (relationship_id, subject_id, self._creator_party_id),
                    )
                ).fetchone()
                if visible is None:
                    raise CreatorRelationshipViolation(
                        "RELATIONSHIP-QUERY-NOT-FOUND"
                    )
                rows = await (
                    await connection.execute(
                        """
                        SELECT relationship_revision_id, revision_no, facts,
                               interpretation, boundaries, commitments,
                               open_issues, commitment_event,
                               relationship_status, created_at
                        FROM armi.relationship_revisions
                        WHERE relationship_id = %s AND privacy_scope = 'private'
                        ORDER BY revision_no DESC
                        LIMIT %s
                        """,
                        (relationship_id, _PAGE_SIZE + 1),
                    )
                ).fetchall()
        except CreatorRelationshipViolation:
            raise
        except (psycopg.Error, PoolTimeout):
            raise CreatorRelationshipViolation(
                "RELATIONSHIP-QUERY-UNAVAILABLE"
            ) from None
        return CreatorRelationshipTimeline(
            relationship_id,
            tuple(_revision(row) for row in rows[:_PAGE_SIZE]),
            len(rows) > _PAGE_SIZE,
        )

    async def _scope(
        self, connection: psycopg.AsyncConnection[tuple[Any, ...]]
    ) -> UUID:
        row = await (
            await connection.execute(
                """
                SELECT subject.subject_id
                FROM armi.subjects AS subject
                JOIN armi.parties AS creator
                  ON creator.party_id = %s
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                WHERE subject.singleton_key = 1
                """,
                (self._creator_party_id,),
            )
        ).fetchone()
        if row is None or not isinstance(row[0], UUID):
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE")
        return row[0]


def _objects(value: object, keys: frozenset[str]) -> tuple[dict[str, object], ...]:
    if type(value) is not list:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
    items = cast(list[object], value)
    if any(type(item) is not dict or frozenset(item) != keys for item in items):
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
    return tuple(cast(dict[str, object], item) for item in items)


def _text(item: dict[str, object], key: str) -> str:
    value = item[key]
    if type(value) is not str or not value:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
    return value


def _row_text(value: object) -> str:
    if type(value) is not str or not value:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
    return value


def _uuid(item: dict[str, object], key: str) -> UUID:
    value = _text(item, key)
    try:
        parsed = UUID(value)
    except ValueError:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE") from None
    if parsed.version != 7 or str(parsed) != value:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
    return parsed


def _facts(value: object) -> tuple[RelationshipFact, ...]:
    return tuple(
        RelationshipFact(
            RelationshipFactKind(_text(item, "kind")),
            _text(item, "summary"),
        )
        for item in _objects(value, frozenset({"kind", "summary"}))
    )


def _boundaries(value: object) -> tuple[RelationshipBoundary, ...]:
    return tuple(
        RelationshipBoundary(
            RelationshipPartyRole(_text(item, "party_role")),
            RelationshipBoundaryKind(_text(item, "kind")),
            RelationshipBoundaryAction(_text(item, "action")),
            _text(item, "summary"),
        )
        for item in _objects(
            value, frozenset({"party_role", "kind", "action", "summary"})
        )
    )


def _commitments(value: object) -> tuple[RelationshipCommitment, ...]:
    return tuple(
        RelationshipCommitment(
            _uuid(item, "commitment_id"),
            RelationshipPartyRole(_text(item, "party_role")),
            _text(item, "scope"),
            _text(item, "content"),
            RelationshipCommitmentStatus(_text(item, "status")),
            RelationshipCommitmentEventKind(_text(item, "last_event_kind")),
            _text(item, "last_event_summary"),
        )
        for item in _objects(
            value,
            frozenset(
                {
                    "commitment_id",
                    "party_role",
                    "scope",
                    "content",
                    "status",
                    "last_event_kind",
                    "last_event_summary",
                }
            ),
        )
    )


def _issues(value: object) -> tuple[RelationshipIssue, ...]:
    items = _objects(
        value,
        frozenset({"issue_id", "kind", "commitment_ids", "summary", "status"}),
    )
    values: list[RelationshipIssue] = []
    for item in items:
        commitment_ids = item["commitment_ids"]
        if type(commitment_ids) is not list:
            raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE")
        values.append(
            RelationshipIssue(
                _uuid(item, "issue_id"),
                RelationshipIssueKind(_text(item, "kind")),
                tuple(_uuid({"value": value}, "value") for value in commitment_ids),
                _text(item, "summary"),
                RelationshipIssueStatus(_text(item, "status")),
            )
        )
    return tuple(values)


def _commitment_event(value: object) -> RelationshipCommitmentEvent | None:
    if value is None:
        return None
    items = _objects(
        [value],
        frozenset({"commitment_id", "kind", "summary", "related_commitment_id"}),
    )
    item = items[0]
    related = item["related_commitment_id"]
    return RelationshipCommitmentEvent(
        _uuid(item, "commitment_id"),
        RelationshipCommitmentEventKind(_text(item, "kind")),
        _text(item, "summary"),
        None if related is None else _uuid({"value": related}, "value"),
    )


def _revision(row: tuple[Any, ...]) -> CreatorRelationshipRevision:
    try:
        return CreatorRelationshipRevision(
            relationship_revision_id=row[0],
            revision_no=row[1],
            facts=_facts(row[2]),
            interpretation=_row_text(row[3]),
            boundaries=_boundaries(row[4]),
            commitments=_commitments(row[5]),
            open_issues=_issues(row[6]),
            commitment_event=_commitment_event(row[7]),
            status=RelationshipStatus(_row_text(row[8])),
            occurred_at=row[9],
        )
    except (CandidateViolation, IndexError, ValueError, TypeError):
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-SHAPE") from None


__all__ = ("PostgreSQLCreatorRelationshipQuery",)
