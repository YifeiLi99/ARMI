"""PostgreSQL implementation of the subjective-memory owner."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid7

import psycopg
import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_runtime_foundation import PostgreSQLTransaction
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from ._application import MemoryApplication
from ._domain import validate_transition
from .api import (
    CREATOR_MEMORY_PROJECTION_VERSION,
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    CreatorMemoryItem,
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    CreatorMemoryTimelineItem,
    MemoryAccessibility,
    MemoryContextItem,
    MemoryLifeRecordItem,
    MemoryProjectionSource,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemorySourceKind,
    MemoryViolation,
    RecalledMemories,
)

_SEARCH_PATH = "pg_catalog, armi"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    result = base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )
    if _b64encode(result) != value:
        raise ValueError
    return result


class _CursorCodec:
    def __init__(
        self, key: bytes, environment_id: UUID, creator_party_id: UUID
    ) -> None:
        self._key = key
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id

    def encode(self, resource: str, boundary: dict[str, object]) -> OpaqueCursor:
        payload = {
            "contract_version": "1.0",
            "projection_version": CREATOR_MEMORY_PROJECTION_VERSION,
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            "resource": resource,
            **boundary,
        }
        encoded = _b64encode(rfc8785.dumps(cast(Any, payload)))
        signature = _b64encode(
            hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return OpaqueCursor(f"v1.{encoded}.{signature}")

    def decode(self, cursor: OpaqueCursor, resource: str) -> dict[str, object]:
        try:
            prefix, encoded, signature = cursor.value.split(".", 2)
            if prefix != "v1" or not hmac.compare_digest(
                _b64decode(signature),
                hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest(),
            ):
                raise ValueError
            raw = _b64decode(encoded)
            value = json.loads(raw)
            if type(value) is not dict or rfc8785.dumps(cast(Any, value)) != raw:
                raise ValueError
            item = cast(dict[str, object], value)
            fixed = {
                "contract_version": "1.0",
                "projection_version": CREATOR_MEMORY_PROJECTION_VERSION,
                "environment_id": str(self._environment_id),
                "creator_party_id": str(self._creator_party_id),
                "resource": resource,
            }
            if any(item.get(key) != expected for key, expected in fixed.items()):
                raise ValueError
            return item
        except UnicodeError, ValueError, TypeError, json.JSONDecodeError:
            raise MemoryViolation("MEMORY-CURSOR") from None


async def _configure(connection: psycopg.AsyncConnection[Any]) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[Any]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLMemoryOwner:
    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        environment_id: UUID,
        creator_party_id: UUID,
        cursor_key: bytes,
        pool_timeout_seconds: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = expected_role
        self._pool_timeout_seconds = pool_timeout_seconds
        self._codec = _CursorCodec(cursor_key, environment_id, creator_party_id)

        async def check(connection: psycopg.AsyncConnection[Any]) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (expected_role, expected_role, _SEARCH_PATH):
                raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE")

        self._pool = AsyncConnectionPool(
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-memory",
        )
        self._application = MemoryApplication()

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def _read_connection(
        self,
    ) -> AsyncGenerator[psycopg.AsyncConnection[Any]]:
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as conn,
                conn.transaction(),
            ):
                await conn.execute("SET TRANSACTION READ ONLY")
                yield conn
        except MemoryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE") from None

    async def maintenance_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        enabled: bool,
        limit: int = 8,
    ) -> tuple[MemoryContextItem, ...]:
        if not enabled:
            return ()
        rows = await (
            await transaction.execute(
                """
                SELECT memory.memory_id, memory.current_revision_id,
                       memory.head_version, revision.source_fact_class,
                       revision.source_kind, revision.summary,
                       revision.uncertainty, revision.accessibility
                FROM armi.subjective_memories AS memory
                JOIN armi.subjective_memory_revisions AS revision
                  ON revision.memory_revision_id=memory.current_revision_id
                WHERE memory.subject_id=%s AND memory.life_generation_id=%s
                  AND revision.accessibility IN ('available','faded')
                  AND NOT EXISTS (
                    SELECT 1 FROM armi.deletion_items AS item
                    WHERE item.target_kind='memory'
                      AND item.target_ref=memory.memory_id
                      AND item.result_status IN ('completed','partial'))
                ORDER BY CASE revision.accessibility WHEN 'available' THEN 1 ELSE 2 END,
                         revision.created_at DESC, memory.memory_id
                LIMIT %s
                """,
                (subject_id, generation_id, limit),
            )
        ).fetchall()
        return tuple(self._context_item(row) for row in rows)

    async def candidate_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        episode_id: UUID,
    ) -> tuple[MemoryContextItem, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT memory.memory_id, memory.current_revision_id,
                       memory.head_version, revision.source_fact_class,
                       revision.source_kind, revision.summary,
                       revision.uncertainty, revision.accessibility
                FROM armi.cognitive_context_items AS item
                JOIN armi.subjective_memories AS memory
                  ON memory.memory_id=item.source_ref
                 AND memory.subject_id=%s AND memory.head_version=item.source_version
                JOIN armi.subjective_memory_revisions AS revision
                  ON revision.memory_revision_id=memory.current_revision_id
                WHERE item.cognitive_episode_id=%s
                  AND item.disposition='included' AND item.section='memory'
                  AND item.item_kind='current_memory'
                  AND item.source_kind='subjective_memory'
                ORDER BY item.ordinal
                """,
                (subject_id, episode_id),
            )
        ).fetchall()
        return tuple(self._context_item(row) for row in rows)

    @staticmethod
    def _context_item(row: tuple[Any, ...]) -> MemoryContextItem:
        return MemoryContextItem(
            row[0],
            row[1],
            int(row[2]),
            CandidateFactClass(str(row[3])),
            MemorySourceKind(str(row[4])),
            str(row[5]),
            None if row[6] is None else str(row[6]),
            MemoryAccessibility(str(row[7])),
        )

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[MemoryLifeRecordItem, ...]:
        rows = await (
            await transaction.execute(
                """
                SELECT memory.memory_id, revision.summary, revision.source_kind,
                       revision.created_at, revision.accessibility <> 'forgotten'
                FROM armi.subjective_memories AS memory
                JOIN armi.subjective_memory_revisions AS revision
                  ON revision.memory_revision_id=memory.current_revision_id
                WHERE memory.subject_id=%s
                  AND (%s::text IS NULL OR revision.summary ILIKE '%%' || %s || '%%')
                  AND (%s::timestamptz IS NULL OR
                       (revision.created_at, 'memory'::text, memory.memory_id) < (%s,%s,%s))
                  AND NOT EXISTS (
                    SELECT 1 FROM armi.deletion_items AS item
                    WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                      AND item.result_status IN ('completed','partial'))
                ORDER BY revision.created_at DESC, memory.memory_id DESC LIMIT %s
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
            MemoryLifeRecordItem(row[0], str(row[1]), str(row[2]), row[3], bool(row[4]))
            for row in rows
        )

    async def _creator_subject(self, connection: Any) -> UUID:
        creator = await (
            await connection.execute(
                """SELECT 1 FROM armi.parties WHERE party_id=%s
                   AND party_kind='creator' AND creator_role='unique_primary_creator'
                   AND status='active'""",
                (self._creator_party_id,),
            )
        ).fetchone()
        row = await (
            await connection.execute(
                "SELECT subject_id FROM armi.subjects WHERE singleton_key=1"
            )
        ).fetchone()
        if creator is None or row is None:
            raise MemoryViolation("MEMORY-QUERY-NOT-AUTHORIZED")
        return row[0]

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryPage:
        boundary: tuple[datetime, UUID] | None = None
        if cursor is not None:
            item = self._codec.decode(cursor, "memory_current")
            try:
                boundary = (
                    Instant.from_wire(item["before_at"]).value,
                    UUID(str(item["before_id"])),
                )
            except KeyError, TypeError, ValueError:
                raise MemoryViolation("MEMORY-CURSOR") from None
        async with self._read_connection() as connection:
            subject_id = await self._creator_subject(connection)
            rows = await (
                await connection.execute(
                    """
                    SELECT memory.memory_id, revision.summary, revision.uncertainty,
                           revision.source_kind, revision.source_fact_class,
                           revision.accessibility, revision.revision_kind,
                           revision.revision_no, memory.head_version,
                           memory.created_at, revision.created_at
                    FROM armi.subjective_memories AS memory
                    JOIN armi.subjective_memory_revisions AS revision
                      ON revision.memory_revision_id=memory.current_revision_id
                    WHERE memory.subject_id=%s
                      AND (%s::text IS NULL OR revision.summary ILIKE '%%'||%s||'%%')
                      AND (%s::timestamptz IS NULL OR
                           (revision.created_at,memory.memory_id)<(%s,%s))
                      AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                        WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                          AND item.result_status IN ('completed','partial'))
                    ORDER BY revision.created_at DESC,memory.memory_id DESC LIMIT %s
                    """,
                    (
                        subject_id,
                        query_text,
                        query_text,
                        None if boundary is None else boundary[0],
                        None if boundary is None else boundary[0],
                        None if boundary is None else boundary[1],
                        limit + 1,
                    ),
                )
            ).fetchall()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = self._codec.encode(
                "memory_current",
                {
                    "before_at": Instant(visible[-1][10]).to_wire(),
                    "before_id": str(visible[-1][0]),
                },
            )
        return CreatorMemoryPage(
            tuple(self._creator_item(row) for row in visible), next_cursor
        )

    @staticmethod
    def _creator_item(row: tuple[Any, ...]) -> CreatorMemoryItem:
        return CreatorMemoryItem(
            row[0],
            str(row[1]),
            None if row[2] is None else str(row[2]),
            str(row[3]),
            str(row[4]),
            MemoryAccessibility(str(row[5])),
            MemoryRevisionKind(str(row[6])),
            int(row[7]),
            int(row[8]),
            Instant(row[9]),
            Instant(row[10]),
        )

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryTimeline:
        before_no: int | None = None
        if cursor is not None:
            item = self._codec.decode(cursor, f"memory_timeline:{memory_id}")
            before_no = cast(int, item.get("before_revision_no"))
            if type(before_no) is not int or before_no < 1:
                raise MemoryViolation("MEMORY-CURSOR")
        async with self._read_connection() as connection:
            subject_id = await self._creator_subject(connection)
            exists = await (
                await connection.execute(
                    """SELECT 1 FROM armi.subjective_memories AS memory
                       WHERE memory.memory_id=%s AND memory.subject_id=%s
                         AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                           WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                             AND item.result_status IN ('completed','partial'))""",
                    (memory_id, subject_id),
                )
            ).fetchone()
            if exists is None:
                raise MemoryViolation("MEMORY-QUERY-NOT-FOUND")
            rows = await (
                await connection.execute(
                    """
                    SELECT revision.memory_revision_id, revision.revision_no,
                           revision.revision_kind, revision.accessibility,
                           revision.summary, revision.uncertainty,
                           revision.source_kind, revision.source_fact_class,
                           relation.relation_kind, relation.to_memory_id,
                           revision.created_at
                    FROM armi.subjective_memory_revisions AS revision
                    LEFT JOIN LATERAL (
                      SELECT relation_kind,to_memory_id FROM armi.memory_relations
                      WHERE from_memory_revision_id=revision.memory_revision_id
                      ORDER BY memory_relation_id DESC LIMIT 1) AS relation ON TRUE
                    WHERE revision.memory_id=%s
                      AND (%s::bigint IS NULL OR revision.revision_no<%s)
                    ORDER BY revision.revision_no DESC LIMIT %s
                    """,
                    (memory_id, before_no, before_no, limit + 1),
                )
            ).fetchall()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = self._codec.encode(
                f"memory_timeline:{memory_id}",
                {"before_revision_no": int(visible[-1][1])},
            )
        return CreatorMemoryTimeline(
            memory_id, tuple(self._timeline_item(row) for row in visible), next_cursor
        )

    @staticmethod
    def _timeline_item(row: tuple[Any, ...]) -> CreatorMemoryTimelineItem:
        return CreatorMemoryTimelineItem(
            row[0],
            int(row[1]),
            MemoryRevisionKind(str(row[2])),
            MemoryAccessibility(str(row[3])),
            str(row[4]),
            None if row[5] is None else str(row[5]),
            str(row[6]),
            str(row[7]),
            None if row[8] is None else MemoryRelationKind(str(row[8])),
            row[9],
            Instant(row[10]),
        )

    def _memory_drafts(self, drafts: tuple[CandidateOwnerDraft, ...]):
        return tuple(
            self._application.decode(item.canonical_payload)
            for item in drafts
            if item.owner == "memory"
        )

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool:
        revisions = tuple(
            item
            for item in self._memory_drafts(drafts)
            if type(item) is CandidateMemoryRevisionDraft
        )
        for memory_id in sorted({item.memory_id for item in revisions}, key=str):
            row = await (
                await transaction.execute(
                    """SELECT current_revision_id,head_version
                       FROM armi.subjective_memories
                       WHERE memory_id=%s AND subject_id=%s FOR UPDATE""",
                    (memory_id, subject_id),
                )
            ).fetchone()
            expected = next(item for item in revisions if item.memory_id == memory_id)
            if row is None or row != (
                expected.current_revision_id,
                expected.expected_head_version,
            ):
                return False
        return True

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        validation_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        experience_ids: dict[str, UUID],
    ) -> tuple[UUID, ...]:
        affected: list[UUID] = []
        for value in self._memory_drafts(drafts):
            valid = await (
                await transaction.execute(
                    """SELECT 1 FROM armi.cognitive_candidate_validation_items
                       WHERE candidate_validation_id=%s AND proposal_ref=%s
                         AND owner_kind='memory' AND validation_status='accepted'""",
                    (validation_id, value.proposal_ref),
                )
            ).fetchone()
            if valid is None:
                raise MemoryViolation("MEMORY-VALIDATION")
            if isinstance(value, CandidateMemoryDraft):
                source = experience_ids.get(value.source_experience_ref)
                if source is None:
                    raise MemoryViolation("MEMORY-SOURCE")
                memory_id, revision_id = uuid7(), uuid7()
                await transaction.execute(
                    """INSERT INTO armi.subjective_memories
                       (memory_id,subject_id,life_generation_id,current_revision_id,head_version)
                       VALUES (%s,%s,%s,%s,1)""",
                    (memory_id, subject_id, generation_id, revision_id),
                )
                await transaction.execute(
                    """INSERT INTO armi.subjective_memory_revisions
                       (memory_revision_id,memory_id,revision_no,previous_revision_id,
                        subject_commit_id,candidate_validation_id,proposal_ref,
                        source_experience_id,source_kind,source_fact_class,summary,
                        uncertainty,revision_kind,accessibility,mechanism_identity,
                        mechanism_config_identity,privacy_scope)
                       SELECT %s,%s,1,NULL,%s,%s,%s,%s,%s,%s,%s,
                              experience.uncertainty,'formed','available',%s,
                              'formation-v1','private'
                       FROM armi.accepted_experiences AS experience
                       WHERE experience.experience_id=%s""",
                    (
                        revision_id,
                        memory_id,
                        commit_id,
                        validation_id,
                        value.proposal_ref,
                        source,
                        value.source_kind.value,
                        value.fact_class.value,
                        value.summary,
                        value.mechanism_identity,
                        source,
                    ),
                )
                affected.append(memory_id)
                continue
            row = await (
                await transaction.execute(
                    """SELECT memory.current_revision_id,memory.head_version,
                              revision.revision_no,revision.source_experience_id,
                              revision.source_kind,revision.source_fact_class,
                              revision.accessibility
                       FROM armi.subjective_memories AS memory
                       JOIN armi.subjective_memory_revisions AS revision
                         ON revision.memory_revision_id=memory.current_revision_id
                       WHERE memory.memory_id=%s AND memory.subject_id=%s
                         AND memory.life_generation_id=%s FOR UPDATE OF memory""",
                    (value.memory_id, subject_id, generation_id),
                )
            ).fetchone()
            if (
                row is None
                or row[0] != value.current_revision_id
                or int(row[1]) != value.expected_head_version
            ):
                raise MemoryViolation("MEMORY-HEAD-STALE")
            validate_transition(MemoryAccessibility(str(row[6])), value)
            revision_id = uuid7()
            await transaction.execute(
                """INSERT INTO armi.subjective_memory_revisions
                   (memory_revision_id,memory_id,revision_no,previous_revision_id,
                    subject_commit_id,candidate_validation_id,proposal_ref,
                    source_experience_id,source_kind,source_fact_class,summary,
                    uncertainty,revision_kind,accessibility,mechanism_identity,
                    mechanism_config_identity,privacy_scope)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'private')""",
                (
                    revision_id,
                    value.memory_id,
                    int(row[2]) + 1,
                    value.current_revision_id,
                    commit_id,
                    validation_id,
                    value.proposal_ref,
                    row[3],
                    value.source_kind.value,
                    value.fact_class.value,
                    value.summary,
                    value.uncertainty,
                    value.revision_kind.value,
                    value.accessibility.value,
                    value.mechanism_identity,
                    value.mechanism_config_identity,
                ),
            )
            updated = await (
                await transaction.execute(
                    """UPDATE armi.subjective_memories SET current_revision_id=%s,
                              head_version=head_version+1
                       WHERE memory_id=%s AND current_revision_id=%s AND head_version=%s
                       RETURNING memory_id""",
                    (
                        revision_id,
                        value.memory_id,
                        value.current_revision_id,
                        value.expected_head_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise MemoryViolation("MEMORY-HEAD-STALE")
            if value.accessibility is MemoryAccessibility.FORGOTTEN:
                await transaction.execute(
                    "DELETE FROM armi.context_embedding_projections WHERE source_kind='subjective_memory' AND source_ref=%s",
                    (value.memory_id,),
                )
            if value.related_memory_id is not None:
                related = await (
                    await transaction.execute(
                        """SELECT 1 FROM armi.subjective_memories
                           WHERE memory_id=%s AND subject_id=%s AND life_generation_id=%s""",
                        (value.related_memory_id, subject_id, generation_id),
                    )
                ).fetchone()
                if related is None or value.relation_kind is None:
                    raise MemoryViolation("MEMORY-RELATION")
                await transaction.execute(
                    """INSERT INTO armi.memory_relations
                       (memory_relation_id,from_memory_id,from_memory_revision_id,
                        to_memory_id,relation_kind,subject_commit_id,
                        candidate_validation_id,proposal_ref)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        uuid7(),
                        value.memory_id,
                        revision_id,
                        value.related_memory_id,
                        value.relation_kind.value,
                        commit_id,
                        validation_id,
                        value.proposal_ref,
                    ),
                )
            affected.append(value.memory_id)
        return tuple(affected)

    async def affected_memory_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT memory_id FROM armi.subjective_memory_revisions
                   WHERE candidate_validation_id=%s ORDER BY memory_id""",
                (validation_id,),
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def next_missing_source(
        self, transaction: PostgreSQLTransaction, *, model_binding: str
    ) -> MemoryProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT memory.subject_id,memory.life_generation_id,memory.memory_id,
                          memory.head_version,revision.summary
                   FROM armi.subjective_memories AS memory
                   JOIN armi.subjective_memory_revisions AS revision
                     ON revision.memory_revision_id=memory.current_revision_id
                   WHERE revision.accessibility IN ('available','faded')
                     AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                       WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                         AND item.result_status IN ('completed','partial'))
                     AND NOT EXISTS (SELECT 1 FROM armi.context_embedding_projections AS projection
                       WHERE projection.source_kind='subjective_memory'
                         AND projection.source_ref=memory.memory_id
                         AND projection.source_version=memory.head_version
                         AND projection.model_binding=%s)
                     AND NOT EXISTS (SELECT 1 FROM armi.durable_work AS work
                       WHERE work.owner_kind='subjective_memory'
                         AND work.owner_ref=memory.memory_id
                         AND work.work_kind='context.embedding.project'
                         AND work.status IN ('ready','leased'))
                   ORDER BY memory.memory_id LIMIT 1""",
                (model_binding,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else MemoryProjectionSource(
                row[0], row[1], row[2], int(row[3]), str(row[4])
            )
        )

    async def load_source(
        self, transaction: PostgreSQLTransaction, memory_id: UUID
    ) -> MemoryProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT memory.subject_id,memory.life_generation_id,memory.memory_id,
                          memory.head_version,revision.summary
                   FROM armi.subjective_memories AS memory
                   JOIN armi.subjective_memory_revisions AS revision
                     ON revision.memory_revision_id=memory.current_revision_id
                   WHERE memory.memory_id=%s AND revision.accessibility IN ('available','faded')
                     AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                       WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                         AND item.result_status IN ('completed','partial'))""",
                (memory_id,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else MemoryProjectionSource(
                row[0], row[1], row[2], int(row[3]), str(row[4])
            )
        )

    async def recall(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        model_binding: str,
        query_vector: tuple[float, ...],
        minimum_similarity: float,
        limit: int,
    ) -> RecalledMemories:
        vector = "[" + ",".join(format(item, ".17g") for item in query_vector) + "]"
        rows = await (
            await transaction.execute(
                """SELECT projection.source_ref,projection.source_version,
                          projection.chunk_text,
                          1-(projection.embedding OPERATOR(armi_extensions.<=>)
                             %s::armi_extensions.vector) AS similarity
                   FROM armi.context_embedding_projections AS projection
                   JOIN armi.subjective_memories AS memory
                     ON memory.memory_id=projection.source_ref
                    AND memory.head_version=projection.source_version
                   JOIN armi.subjective_memory_revisions AS revision
                     ON revision.memory_revision_id=memory.current_revision_id
                   WHERE projection.source_kind='subjective_memory'
                     AND projection.subject_id=%s AND projection.life_generation_id=%s
                     AND projection.model_binding=%s
                     AND revision.accessibility IN ('available','faded')
                     AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                       WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                         AND item.result_status IN ('completed','partial'))
                     AND 1-(projection.embedding OPERATOR(armi_extensions.<=>)
                             %s::armi_extensions.vector)>=%s
                   ORDER BY similarity DESC,projection.source_ref LIMIT %s""",
                (
                    vector,
                    subject_id,
                    generation_id,
                    model_binding,
                    vector,
                    minimum_similarity,
                    limit,
                ),
            )
        ).fetchall()
        missing = await (
            await transaction.execute(
                """SELECT EXISTS (SELECT 1 FROM armi.subjective_memories AS memory
                   JOIN armi.subjective_memory_revisions AS revision
                     ON revision.memory_revision_id=memory.current_revision_id
                   WHERE memory.subject_id=%s AND memory.life_generation_id=%s
                     AND revision.accessibility IN ('available','faded')
                     AND NOT EXISTS (SELECT 1 FROM armi.deletion_items AS item
                       WHERE item.target_kind='memory' AND item.target_ref=memory.memory_id
                         AND item.result_status IN ('completed','partial'))
                     AND NOT EXISTS (SELECT 1 FROM armi.context_embedding_projections AS projection
                       WHERE projection.source_kind='subjective_memory'
                         AND projection.source_ref=memory.memory_id
                         AND projection.source_version=memory.head_version
                         AND projection.model_binding=%s))""",
                (subject_id, generation_id, model_binding),
            )
        ).fetchone()
        return RecalledMemories(
            tuple((row[0], int(row[1]), str(row[2]), float(row[3])) for row in rows),
            bool(missing and missing[0]),
        )

    async def find_for_party(
        self, transaction: PostgreSQLTransaction, party_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT revision.memory_id
                   FROM armi.subjective_memory_revisions AS revision
                   JOIN armi.experience_evidence_links AS link
                     ON link.experience_id=revision.source_experience_id
                   JOIN armi.external_evidence AS evidence ON evidence.evidence_id=link.evidence_id
                   WHERE evidence.context_party_id=%s ORDER BY revision.memory_id""",
                (party_id,),
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def clear_projections(
        self, transaction: PostgreSQLTransaction, *, memory_ids: tuple[UUID, ...]
    ) -> None:
        if memory_ids:
            await transaction.execute(
                """DELETE FROM armi.context_embedding_projections
                   WHERE source_kind='subjective_memory' AND source_ref=ANY(%s)""",
                (list(memory_ids),),
            )


__all__ = ("PostgreSQLMemoryOwner",)
