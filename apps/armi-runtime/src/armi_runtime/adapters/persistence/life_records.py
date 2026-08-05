"""PostgreSQL exact life-record and Creator memory projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_kernel.application import (
    CreatorMemoryItem,
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    CreatorMemoryTimelineItem,
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
)
from armi_kernel.application.life_records import (
    MemoryAccessibility,
    MemoryRelationKind,
    MemoryRevisionKind,
)
from armi_kernel.contracts import Instant, OpaqueCursor
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .role_policy import physical_role_name

_SEARCH_PATH = "pg_catalog, armi"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    decoded = base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


class LifeRecordCursorCodec:
    """Sign one stable boundary and bind it to the complete query scope."""

    __slots__ = ("_creator_party_id", "_environment_id", "_key")

    def __init__(
        self,
        *,
        key: bytes,
        environment_id: UUID,
        creator_party_id: UUID,
    ) -> None:
        if (
            type(key) is not bytes
            or len(key) != hashlib.sha256().digest_size
            or environment_id.version != 7
            or creator_party_id.version != 7
        ):
            raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID")
        self._key = key
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id

    def encode(
        self,
        *,
        scope: Mapping[str, object],
        boundary: Mapping[str, object],
    ) -> OpaqueCursor:
        payload = {
            "contract_version": "1.0",
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            **scope,
            **boundary,
        }
        encoded = _b64encode(rfc8785.dumps(cast(Any, payload)))
        signature = _b64encode(
            hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return OpaqueCursor(f"v1.{encoded}.{signature}")

    def decode(
        self,
        cursor: OpaqueCursor,
        *,
        scope: Mapping[str, object],
        boundary_keys: frozenset[str],
    ) -> dict[str, object]:
        try:
            prefix, encoded, signature = cursor.value.split(".", 2)
            actual = _b64decode(signature)
            expected = hmac.new(
                self._key, encoded.encode("ascii"), hashlib.sha256
            ).digest()
            if prefix != "v1" or not hmac.compare_digest(actual, expected):
                raise ValueError
            raw = _b64decode(encoded)
            payload = cast(dict[str, object], json.loads(raw))
            if rfc8785.dumps(cast(Any, payload)) != raw:
                raise ValueError
        except UnicodeDecodeError, ValueError, json.JSONDecodeError, TypeError:
            raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID") from None
        fixed = {
            "contract_version": "1.0",
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            **scope,
        }
        if set(payload) != {*fixed, *boundary_keys}:
            raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID")
        if any(payload.get(key) != value for key, value in fixed.items()):
            raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-STALE")
        return {key: payload[key] for key in boundary_keys}


async def _configure(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLLifeRecordQuery:
    """Read current life facts without changing memory or subject state."""

    __slots__ = (
        "_codec",
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
        cursor_key: bytes,
        pool_timeout_seconds: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout_seconds = pool_timeout_seconds
        self._codec = LifeRecordCursorCodec(
            key=cursor_key,
            environment_id=environment_id,
            creator_party_id=creator_party_id,
        )

        async def check(
            connection: psycopg.AsyncConnection[tuple[Any, ...]],
        ) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-life-record-query",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._pool.close()

    async def query(self, request: LifeRecordQuery) -> LifeRecordPage:
        scope = {
            "projection_version": "life-record-query.v1",
            "resource": "life_records",
            "actor": request.actor.value,
            "retrieval_kind": request.retrieval_kind.value,
            "record_kind": (
                None if request.record_kind is None else request.record_kind.value
            ),
            "query_text": request.query_text,
            "limit": request.limit,
        }
        boundary: tuple[Instant, str, UUID] | None = None
        if request.cursor is not None:
            raw = self._codec.decode(
                request.cursor,
                scope=scope,
                boundary_keys=frozenset({"before_at", "before_kind", "before_id"}),
            )
            try:
                boundary = (
                    Instant.from_wire(raw["before_at"]),
                    cast(str, raw["before_kind"]),
                    UUID(cast(str, raw["before_id"])),
                )
            except KeyError, TypeError, ValueError:
                raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID") from None
            if (
                boundary[1] not in {item.value for item in LifeRecordKind}
                or boundary[2].version != 7
            ):
                raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID")
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id = await self._scope(connection, request.actor)
                rows = await (
                    await connection.execute(
                        """
                        WITH records AS (
                            SELECT activity.activity_id AS record_ref,
                                   'activity'::text AS record_kind,
                                   left(
                                       revision.goal ||
                                       CASE WHEN revision.progress_summary IS NULL
                                           THEN '' ELSE ' — ' || revision.progress_summary
                                       END,
                                       4096
                                   ) AS summary,
                                   'activity_current'::text AS source_kind,
                                   revision.created_at AS occurred_at,
                                   NULL::boolean AS naturally_recallable
                            FROM armi.activities AS activity
                            JOIN armi.activity_revisions AS revision
                              ON revision.activity_revision_id =
                                 activity.current_revision_id
                            WHERE activity.subject_id = %s
                            UNION ALL
                            SELECT experience.experience_id,
                                   'conversation'::text,
                                   experience.first_person_gist,
                                   experience.source_perspective,
                                   experience.created_at,
                                   NULL::boolean
                            FROM armi.accepted_experiences AS experience
                            JOIN armi.subject_commits AS commit
                              ON commit.subject_commit_id =
                                 experience.subject_commit_id
                            WHERE commit.subject_id = %s
                            UNION ALL
                            SELECT memory.memory_id,
                                   'memory'::text,
                                   revision.summary,
                                   revision.source_kind,
                                   revision.created_at,
                                   revision.accessibility <> 'forgotten'
                            FROM armi.subjective_memories AS memory
                            JOIN armi.subjective_memory_revisions AS revision
                              ON revision.memory_revision_id =
                                 memory.current_revision_id
                            WHERE memory.subject_id = %s
                            UNION ALL
                            SELECT relationship.relationship_id,
                                   'relationship'::text,
                                   revision.interpretation,
                                   'relationship_current'::text,
                                   revision.created_at,
                                   NULL::boolean
                            FROM armi.relationships AS relationship
                            JOIN armi.relationship_revisions AS revision
                              ON revision.relationship_revision_id =
                                 relationship.current_revision_id
                            WHERE relationship.subject_id = %s
                            UNION ALL
                            SELECT revision.component_revision_id,
                                   'self_change'::text,
                                   left(revision.semantic_payload::text, 4096),
                                   revision.origin_kind,
                                   revision.created_at,
                                   NULL::boolean
                            FROM armi.subject_component_revisions AS revision
                            WHERE revision.subject_id = %s
                              AND revision.component_kind = 'self'
                        )
                        SELECT record_ref, record_kind, summary, source_kind,
                               occurred_at, naturally_recallable
                        FROM records
                        WHERE (%s::text IS NULL OR record_kind = %s)
                          AND (%s::text IS NULL OR summary ILIKE
                               '%%' || %s || '%%')
                          AND (
                              %s::timestamptz IS NULL
                              OR (occurred_at, record_kind, record_ref)
                                 < (%s, %s, %s)
                          )
                        ORDER BY occurred_at DESC, record_kind DESC,
                                 record_ref DESC
                        LIMIT %s
                        """,
                        (
                            subject_id,
                            subject_id,
                            subject_id,
                            subject_id,
                            subject_id,
                            None
                            if request.record_kind is None
                            else request.record_kind.value,
                            None
                            if request.record_kind is None
                            else request.record_kind.value,
                            request.query_text,
                            request.query_text,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[1],
                            None if boundary is None else boundary[2],
                            request.limit + 1,
                        ),
                    )
                ).fetchall()
        except LifeRecordQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
        visible = rows[: request.limit]
        next_cursor = None
        if len(rows) > request.limit and visible:
            oldest = visible[-1]
            next_cursor = self._codec.encode(
                scope=scope,
                boundary={
                    "before_at": Instant(cast(datetime, oldest[4])).to_wire(),
                    "before_kind": str(oldest[1]),
                    "before_id": str(oldest[0]),
                },
            )
        return LifeRecordPage(
            items=tuple(
                LifeRecordItem(
                    record_ref=row[0],
                    record_kind=LifeRecordKind(str(row[1])),
                    summary=str(row[2]),
                    source_kind=str(row[3]),
                    occurred_at=Instant(cast(datetime, row[4])),
                    naturally_recallable=cast(bool | None, row[5]),
                    retrieval_kind=request.retrieval_kind,
                )
                for row in visible
            ),
            next_cursor=next_cursor,
        )

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryPage:
        request = LifeRecordQuery(
            actor=LifeRecordActor.CREATOR,
            retrieval_kind=LifeRecordRetrievalKind.CREATOR_VIEW,
            limit=limit,
            record_kind=LifeRecordKind.MEMORY,
            query_text=query_text,
            cursor=cursor,
        )
        scope = {
            "projection_version": "creator-memory.v1",
            "resource": "memory_current",
            "query_text": request.query_text,
            "limit": request.limit,
        }
        boundary: tuple[Instant, UUID] | None = None
        if cursor is not None:
            raw = self._codec.decode(
                cursor,
                scope=scope,
                boundary_keys=frozenset({"before_at", "before_id"}),
            )
            try:
                boundary = (
                    Instant.from_wire(raw["before_at"]),
                    UUID(cast(str, raw["before_id"])),
                )
            except KeyError, TypeError, ValueError:
                raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID") from None
            if boundary[1].version != 7:
                raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID")
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id = await self._scope(connection, LifeRecordActor.CREATOR)
                rows = await (
                    await connection.execute(
                        """
                        SELECT memory.memory_id, revision.summary,
                               revision.uncertainty, revision.source_kind,
                               revision.source_fact_class,
                               revision.accessibility, revision.revision_kind,
                               revision.revision_no, memory.head_version,
                               memory.created_at, revision.created_at
                        FROM armi.subjective_memories AS memory
                        JOIN armi.subjective_memory_revisions AS revision
                          ON revision.memory_revision_id = memory.current_revision_id
                        WHERE memory.subject_id = %s
                          AND (%s::text IS NULL OR revision.summary ILIKE
                               '%%' || %s || '%%')
                          AND (
                              %s::timestamptz IS NULL
                              OR (revision.created_at, memory.memory_id)
                                 < (%s, %s)
                          )
                        ORDER BY revision.created_at DESC, memory.memory_id DESC
                        LIMIT %s
                        """,
                        (
                            subject_id,
                            query_text,
                            query_text,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[1],
                            limit + 1,
                        ),
                    )
                ).fetchall()
        except LifeRecordQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            oldest = visible[-1]
            next_cursor = self._codec.encode(
                scope=scope,
                boundary={
                    "before_at": Instant(cast(datetime, oldest[10])).to_wire(),
                    "before_id": str(oldest[0]),
                },
            )
        return CreatorMemoryPage(
            items=tuple(self._memory_item(row) for row in visible),
            next_cursor=next_cursor,
        )

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryTimeline:
        if memory_id.version != 7 or type(limit) is not int or not 1 <= limit <= 100:
            raise LifeRecordQueryViolation("CON-LIFE-QUERY-REQUEST")
        scope = {
            "projection_version": "creator-memory.v1",
            "resource": "memory_timeline",
            "memory_id": str(memory_id),
            "limit": limit,
        }
        before_revision_no: int | None = None
        if cursor is not None:
            raw = self._codec.decode(
                cursor,
                scope=scope,
                boundary_keys=frozenset({"before_revision_no"}),
            )
            value = raw.get("before_revision_no")
            if type(value) is not int or value < 1:
                raise LifeRecordQueryViolation("LIFE-QUERY-CURSOR-INVALID")
            before_revision_no = value
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                subject_id = await self._scope(connection, LifeRecordActor.CREATOR)
                visible = await (
                    await connection.execute(
                        """
                        SELECT 1 FROM armi.subjective_memories
                        WHERE memory_id = %s AND subject_id = %s
                        """,
                        (memory_id, subject_id),
                    )
                ).fetchone()
                if visible is None:
                    raise LifeRecordQueryViolation("LIFE-QUERY-NOT-FOUND")
                rows = await (
                    await connection.execute(
                        """
                        SELECT revision.memory_revision_id,
                               revision.revision_no, revision.revision_kind,
                               revision.accessibility, revision.summary,
                               revision.uncertainty, revision.source_kind,
                               revision.source_fact_class,
                               relation.relation_kind,
                               relation.to_memory_id,
                               revision.created_at
                        FROM armi.subjective_memory_revisions AS revision
                        LEFT JOIN LATERAL (
                            SELECT item.relation_kind, item.to_memory_id
                            FROM armi.memory_relations AS item
                            WHERE item.from_memory_revision_id =
                                  revision.memory_revision_id
                            ORDER BY item.created_at DESC,
                                     item.memory_relation_id DESC
                            LIMIT 1
                        ) AS relation ON true
                        WHERE revision.memory_id = %s
                          AND (%s::bigint IS NULL OR revision.revision_no < %s)
                        ORDER BY revision.revision_no DESC
                        LIMIT %s
                        """,
                        (memory_id, before_revision_no, before_revision_no, limit + 1),
                    )
                ).fetchall()
        except LifeRecordQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
        items = rows[:limit]
        next_cursor = None
        if len(rows) > limit and items:
            next_cursor = self._codec.encode(
                scope=scope,
                boundary={"before_revision_no": int(items[-1][1])},
            )
        return CreatorMemoryTimeline(
            memory_id=memory_id,
            items=tuple(self._timeline_item(row) for row in items),
            next_cursor=next_cursor,
        )

    async def _scope(
        self,
        connection: psycopg.AsyncConnection[tuple[Any, ...]],
        actor: LifeRecordActor,
    ) -> UUID:
        if actor is LifeRecordActor.CREATOR:
            creator = await (
                await connection.execute(
                    """
                    SELECT 1 FROM armi.parties
                    WHERE party_id = %s AND party_kind = 'creator'
                      AND creator_role = 'unique_primary_creator'
                      AND status = 'active'
                    """,
                    (self._creator_party_id,),
                )
            ).fetchone()
            if creator is None:
                raise LifeRecordQueryViolation("LIFE-QUERY-NOT-AUTHORIZED")
        row = await (
            await connection.execute(
                "SELECT subject_id FROM armi.subjects WHERE singleton_key = 1"
            )
        ).fetchone()
        if row is None or not isinstance(row[0], UUID):
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
        return row[0]

    @staticmethod
    def _memory_item(row: tuple[Any, ...]) -> CreatorMemoryItem:
        return CreatorMemoryItem(
            memory_id=row[0],
            summary=str(row[1]),
            uncertainty=None if row[2] is None else str(row[2]),
            source_kind=str(row[3]),
            source_fact_class=str(row[4]),
            accessibility=MemoryAccessibility(str(row[5])),
            revision_kind=MemoryRevisionKind(str(row[6])),
            revision_no=int(row[7]),
            head_version=int(row[8]),
            created_at=Instant(cast(datetime, row[9])),
            updated_at=Instant(cast(datetime, row[10])),
        )

    @staticmethod
    def _timeline_item(row: tuple[Any, ...]) -> CreatorMemoryTimelineItem:
        return CreatorMemoryTimelineItem(
            revision_id=row[0],
            revision_no=int(row[1]),
            revision_kind=MemoryRevisionKind(str(row[2])),
            accessibility=MemoryAccessibility(str(row[3])),
            summary=str(row[4]),
            uncertainty=None if row[5] is None else str(row[5]),
            source_kind=str(row[6]),
            source_fact_class=str(row[7]),
            relation_kind=(None if row[8] is None else MemoryRelationKind(str(row[8]))),
            related_memory_id=cast(UUID | None, row[9]),
            occurred_at=Instant(cast(datetime, row[10])),
        )


__all__ = ("LifeRecordCursorCodec", "PostgreSQLLifeRecordQuery")
