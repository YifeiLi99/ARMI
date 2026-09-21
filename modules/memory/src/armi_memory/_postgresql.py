"""PostgreSQL implementation of the subjective-memory owner."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid7

from armi_data_rights.api import DataRightsVisibilityPort
from armi_kernel.application import CandidateFactClass
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorStale,
    RuntimeTransactionFailure,
)

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
    MemoryCandidateSourceRef,
    MemoryContextItem,
    MemoryExperienceSource,
    MemoryLifeRecordItem,
    MemoryProjectionHead,
    MemoryProjectionSource,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemorySourceKind,
    MemoryViolation,
)


class PostgreSQLMemoryOwner:
    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        subject_id: UUID,
        cursor_key: bytes,
        visibility: DataRightsVisibilityPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._factory = factory
        self._codec = ProjectionCursorCodec(
            cursor_key, environment_id, creator_party_id
        )
        self._application = MemoryApplication()
        self._subject_id = subject_id
        self._visibility = visibility

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @asynccontextmanager
    async def _read_connection(
        self,
    ) -> AsyncGenerator[PostgreSQLTransaction]:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                yield unit_of_work.transaction
        except MemoryViolation:
            raise
        except RuntimeTransactionFailure:
            raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE") from None

    async def maintenance_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        enabled: bool,
        limit: int = 8,
    ) -> tuple[MemoryContextItem, ...]:
        if not enabled:
            return ()
        rows = await (
            await transaction.execute(
                """
                SELECT revision.memory_id, revision.memory_revision_id,
                       revision.revision_no, revision.source_fact_class,
                       revision.source_kind, revision.summary,
                       revision.uncertainty, revision.accessibility
                FROM armi.subjective_memory_revisions AS revision
                WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.subject_id=%s
                  AND revision.accessibility IN ('available','faded')
                ORDER BY CASE revision.accessibility WHEN 'available' THEN 1 ELSE 2 END,
                         revision.created_at DESC, revision.memory_id
                LIMIT %s
                """,
                (subject_id, limit * 4),
            )
        ).fetchall()
        hidden = await self._visibility.hidden_targets(
            transaction,
            target_kind="memory",
            target_refs=tuple(row[0] for row in rows),
        )
        return tuple(self._context_item(row) for row in rows if row[0] not in hidden)[
            :limit
        ]

    async def candidate_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        sources: tuple[MemoryCandidateSourceRef, ...],
    ) -> tuple[MemoryContextItem, ...]:
        result: list[MemoryContextItem] = []
        for source in sources:
            row = await (
                await transaction.execute(
                    """
                SELECT revision.memory_id, revision.memory_revision_id,
                       revision.revision_no, revision.source_fact_class,
                       revision.source_kind, revision.summary,
                       revision.uncertainty, revision.accessibility
                FROM armi.subjective_memory_revisions AS revision
                WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.memory_id=%s AND revision.subject_id=%s
                  AND revision.revision_no=%s
                """,
                    (source.memory_id, subject_id, source.head_version),
                )
            ).fetchone()
            if row is None:
                raise MemoryViolation("MEMORY-SOURCE-STALE")
            hidden = await self._visibility.hidden_targets(
                transaction,
                target_kind="memory",
                target_refs=(source.memory_id,),
            )
            if source.memory_id in hidden:
                raise MemoryViolation("MEMORY-SOURCE-STALE")
            result.append(self._context_item(row))
        return tuple(result)

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
                SELECT revision.memory_id, revision.summary, revision.source_kind,
                       revision.created_at, revision.accessibility <> 'forgotten'
                FROM armi.subjective_memory_revisions AS revision
                WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.subject_id=%s
                  AND (%s::text IS NULL OR revision.summary ILIKE '%%' || %s::text || '%%')
                  AND (%s::timestamptz IS NULL OR
                       (revision.created_at, 'memory'::text, revision.memory_id)
                           < (%s::timestamptz,%s::text,%s::uuid))
                ORDER BY revision.created_at DESC, revision.memory_id DESC LIMIT %s
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
        hidden = await self._visibility.hidden_targets(
            transaction,
            target_kind="memory",
            target_refs=tuple(row[0] for row in rows),
        )
        return tuple(
            MemoryLifeRecordItem(row[0], str(row[1]), str(row[2]), row[3], bool(row[4]))
            for row in rows
            if row[0] not in hidden
        )

    def _creator_subject(self) -> UUID:
        return self._subject_id

    async def list_current(
        self,
        *,
        limit: int,
        query_text: str | None = None,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryPage:
        boundary: tuple[datetime, UUID] | None = None
        snapshot_at: datetime | None = None
        if cursor is not None:
            try:
                page = self._codec.decode(
                    cursor,
                    projection_version=CREATOR_MEMORY_PROJECTION_VERSION,
                    resource_kind="memory-current",
                    resource_ref=None,
                    page_limit=limit,
                    query={"query_text": query_text},
                )
                snapshot_at = Instant.from_wire(page.snapshot_ceiling["at"]).value
                boundary = (
                    Instant.from_wire(page.boundary["before_at"]).value,
                    UUID(str(page.boundary["before_id"])),
                )
            except ProjectionCursorStale:
                raise MemoryViolation("MEMORY-CURSOR-STALE") from None
            except KeyError, TypeError, ValueError, ProjectionCursorInvalid:
                raise MemoryViolation("MEMORY-CURSOR") from None
        async with self._read_connection() as connection:
            subject_id = self._creator_subject()
            if snapshot_at is None:
                snapshot_row = await (
                    await connection.execute("SELECT statement_timestamp()")
                ).fetchone()
                if snapshot_row is None:
                    raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE")
                snapshot_at = cast(datetime, snapshot_row[0])
            visible_rows: list[tuple[Any, ...]] = []
            scan_boundary: tuple[datetime, UUID] | None = boundary
            while len(visible_rows) <= limit:
                rows = await (
                    await connection.execute(
                        """
                    SELECT memory.memory_id, revision.summary, revision.uncertainty,
                           revision.source_kind, revision.source_fact_class,
                           revision.accessibility, revision.revision_kind,
                           revision.revision_no, memory.revision_no,
                           memory.memory_created_at, revision.created_at
                    FROM armi.subjective_memory_revisions AS memory
                    JOIN LATERAL (
                      SELECT candidate.*
                      FROM armi.subjective_memory_revisions AS candidate
                      WHERE candidate.memory_id=memory.memory_id
                        AND candidate.created_at<=%s
                      ORDER BY candidate.revision_no DESC LIMIT 1
                    ) AS revision ON TRUE
                    WHERE memory.is_current AND memory.tombstoned_at IS NULL
                      AND memory.subject_id=%s
                      AND memory.memory_created_at<=%s
                      AND (%s::text IS NULL OR revision.summary ILIKE '%%'||%s||'%%')
                      AND (%s::timestamptz IS NULL OR
                           (revision.created_at,memory.memory_id)<(%s,%s))
                    ORDER BY revision.created_at DESC,memory.memory_id DESC LIMIT %s
                    """,
                        (
                            snapshot_at,
                            subject_id,
                            snapshot_at,
                            query_text,
                            query_text,
                            None if scan_boundary is None else scan_boundary[0],
                            None if scan_boundary is None else scan_boundary[0],
                            None if scan_boundary is None else scan_boundary[1],
                            max(limit + 1, 32),
                        ),
                    )
                ).fetchall()
                if not rows:
                    break
                hidden = await self._visibility.hidden_targets(
                    connection,
                    target_kind="memory",
                    target_refs=tuple(row[0] for row in rows),
                )
                visible_rows.extend(row for row in rows if row[0] not in hidden)
                last = rows[-1]
                scan_boundary = (last[10], last[0])
                if len(rows) < max(limit + 1, 32):
                    break
        visible = tuple(visible_rows[:limit])
        next_cursor = None
        if len(visible_rows) > limit and visible:
            next_cursor = self._codec.encode(
                projection_version=CREATOR_MEMORY_PROJECTION_VERSION,
                resource_kind="memory-current",
                resource_ref=None,
                page_limit=limit,
                query={"query_text": query_text},
                snapshot_ceiling={"at": Instant(snapshot_at).to_wire()},
                boundary={
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
        ceiling_no: int | None = None
        if cursor is not None:
            try:
                page = self._codec.decode(
                    cursor,
                    projection_version=CREATOR_MEMORY_PROJECTION_VERSION,
                    resource_kind="memory-timeline",
                    resource_ref=str(memory_id),
                    page_limit=limit,
                    query={},
                )
                ceiling_no = cast(int, page.snapshot_ceiling.get("revision_no"))
                before_no = cast(int, page.boundary.get("before_revision_no"))
            except ProjectionCursorStale:
                raise MemoryViolation("MEMORY-CURSOR-STALE") from None
            except TypeError, ValueError, ProjectionCursorInvalid:
                raise MemoryViolation("MEMORY-CURSOR") from None
            if (
                type(ceiling_no) is not int
                or ceiling_no < 1
                or type(before_no) is not int
                or before_no < 1
            ):
                raise MemoryViolation("MEMORY-CURSOR")
        async with self._read_connection() as connection:
            subject_id = self._creator_subject()
            exists = await (
                await connection.execute(
                    """SELECT 1 FROM armi.subjective_memory_revisions AS revision
                       WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.memory_id=%s AND revision.subject_id=%s""",
                    (memory_id, subject_id),
                )
            ).fetchone()
            hidden = await self._visibility.hidden_targets(
                connection,
                target_kind="memory",
                target_refs=(memory_id,),
            )
            if exists is None or memory_id in hidden:
                raise MemoryViolation("MEMORY-QUERY-NOT-FOUND")
            if ceiling_no is None:
                ceiling_row = await (
                    await connection.execute(
                        """SELECT max(revision_no) FROM armi.subjective_memory_revisions
                           WHERE memory_id=%s""",
                        (memory_id,),
                    )
                ).fetchone()
                if ceiling_row is None or ceiling_row[0] is None:
                    raise MemoryViolation("MEMORY-QUERY-NOT-FOUND")
                ceiling_no = int(ceiling_row[0])
            rows = await (
                await connection.execute(
                    """
                    SELECT revision.memory_revision_id, revision.revision_no,
                           revision.revision_kind, revision.accessibility,
                           revision.summary, revision.uncertainty,
                           revision.source_kind, revision.source_fact_class,
                           revision.relation_kind, revision.related_memory_id,
                           revision.created_at
                    FROM armi.subjective_memory_revisions AS revision
                    WHERE revision.memory_id=%s
                      AND revision.revision_no<=%s
                      AND (%s::bigint IS NULL OR revision.revision_no<%s)
                    ORDER BY revision.revision_no DESC LIMIT %s
                    """,
                    (memory_id, ceiling_no, before_no, before_no, limit + 1),
                )
            ).fetchall()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = self._codec.encode(
                projection_version=CREATOR_MEMORY_PROJECTION_VERSION,
                resource_kind="memory-timeline",
                resource_ref=str(memory_id),
                page_limit=limit,
                query={},
                snapshot_ceiling={"revision_no": ceiling_no},
                boundary={"before_revision_no": int(visible[-1][1])},
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

    def _memory_drafts(
        self,
        drafts: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...],
    ) -> tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...]:
        return drafts

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...],
    ) -> bool:
        revisions = tuple(
            item
            for item in self._memory_drafts(drafts)
            if type(item) is CandidateMemoryRevisionDraft
        )
        for memory_id in sorted({item.memory_id for item in revisions}, key=str):
            await self._lock_memory(transaction, memory_id)
            row = await (
                await transaction.execute(
                    """SELECT memory_revision_id,revision_no
                       FROM armi.subjective_memory_revisions
                       WHERE memory_id=%s AND subject_id=%s AND is_current AND tombstoned_at IS NULL""",
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
        commit_id: UUID,
        validation_id: UUID,
        drafts: tuple[CandidateMemoryDraft | CandidateMemoryRevisionDraft, ...],
        experience_sources: tuple[MemoryExperienceSource, ...],
    ) -> tuple[UUID, ...]:
        affected: list[UUID] = []
        for value in self._memory_drafts(drafts):
            if isinstance(value, CandidateMemoryDraft):
                source = next(
                    (
                        item
                        for item in experience_sources
                        if item.proposal_ref == value.source_experience_ref
                    ),
                    None,
                )
                if source is None:
                    raise MemoryViolation("MEMORY-SOURCE")
                memory_id, revision_id = uuid7(), uuid7()
                await transaction.execute(
                    """INSERT INTO armi.subjective_memory_revisions
                       (memory_revision_id,memory_id,subject_id,memory_created_at,revision_no,previous_revision_id,
                        subject_commit_id,candidate_validation_id,proposal_ref,
                        source_experience_id,source_kind,source_fact_class,summary,
                        uncertainty,revision_kind,accessibility,mechanism_identity,
                        mechanism_config_identity)
                       VALUES (%s,%s,%s,statement_timestamp(),1,NULL,%s,%s,%s,%s,%s,%s,%s,%s,
                               'formed','available',%s,
                               'formation-v1')""",
                    (
                        revision_id,
                        memory_id,
                        subject_id,
                        commit_id,
                        validation_id,
                        value.proposal_ref,
                        source.experience_id,
                        value.source_kind.value,
                        value.fact_class.value,
                        value.summary,
                        source.uncertainty,
                        value.mechanism_identity,
                    ),
                )
                affected.append(memory_id)
                continue
            await self._lock_memory(transaction, value.memory_id)
            row = await (
                await transaction.execute(
                    """SELECT revision.memory_revision_id,revision.revision_no,
                              revision.revision_no,revision.source_experience_id,
                              revision.source_kind,revision.source_fact_class,
                              revision.accessibility,revision.memory_created_at
                       FROM armi.subjective_memory_revisions AS revision
                       WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.memory_id=%s AND revision.subject_id=%s""",
                    (value.memory_id, subject_id),
                )
            ).fetchone()
            if (
                row is None
                or row[0] != value.current_revision_id
                or int(row[1]) != value.expected_head_version
            ):
                raise MemoryViolation("MEMORY-HEAD-STALE")
            validate_transition(MemoryAccessibility(str(row[6])), value)
            if value.related_memory_id is not None:
                related = await (
                    await transaction.execute(
                        """SELECT 1 FROM armi.subjective_memory_revisions
                           WHERE memory_id=%s AND subject_id=%s AND is_current AND tombstoned_at IS NULL""",
                        (value.related_memory_id, subject_id),
                    )
                ).fetchone()
                if related is None or value.relation_kind is None:
                    raise MemoryViolation("MEMORY-RELATION")
            revision_id = uuid7()
            await transaction.execute(
                """UPDATE armi.subjective_memory_revisions SET is_current=false
                   WHERE memory_revision_id=%s""",
                (value.current_revision_id,),
            )
            await transaction.execute(
                """INSERT INTO armi.subjective_memory_revisions
                   (memory_revision_id,memory_id,subject_id,memory_created_at,revision_no,previous_revision_id,
                    subject_commit_id,candidate_validation_id,proposal_ref,
                    source_experience_id,source_kind,source_fact_class,summary,
                    uncertainty,revision_kind,accessibility,mechanism_identity,
                    mechanism_config_identity,related_memory_id,relation_kind)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    revision_id,
                    value.memory_id,
                    subject_id,
                    row[7],
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
                    value.related_memory_id,
                    None if value.relation_kind is None else value.relation_kind.value,
                ),
            )
            affected.append(value.memory_id)
        return tuple(affected)

    @staticmethod
    async def _lock_memory(
        transaction: PostgreSQLTransaction, memory_id: UUID, *, shared: bool = False
    ) -> None:
        # Lock the permanent first row before resolving the current revision.
        # See DESIGN.md: merged content records retain a stable identity.
        await transaction.execute(
            """SELECT memory_revision_id FROM armi.subjective_memory_revisions
               WHERE memory_id=%s AND revision_no=1 FOR SHARE"""
            if shared
            else """SELECT memory_revision_id FROM armi.subjective_memory_revisions
                    WHERE memory_id=%s AND revision_no=1 FOR UPDATE""",
            (memory_id,),
        )

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

    async def projection_head_page(
        self,
        transaction: PostgreSQLTransaction,
        *,
        after_memory_id: UUID | None,
        limit: int = 256,
    ) -> tuple[MemoryProjectionHead, ...]:
        rows = await (
            await transaction.execute(
                """SELECT revision.subject_id,revision.memory_id,revision.revision_no
                   FROM armi.subjective_memory_revisions AS revision
                   WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.accessibility IN ('available','faded')
                     AND (%s::uuid IS NULL OR revision.memory_id>%s)
                   ORDER BY revision.memory_id LIMIT %s""",
                (after_memory_id, after_memory_id, limit),
            )
        ).fetchall()
        return tuple(MemoryProjectionHead(row[0], row[1], int(row[2])) for row in rows)

    async def filter_current_projection_heads(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        sources: tuple[MemoryCandidateSourceRef, ...],
    ) -> tuple[MemoryCandidateSourceRef, ...]:
        if not sources:
            return ()
        rows = await (
            await transaction.execute(
                """WITH requested AS (
                     SELECT memory_id,head_version,ordinal
                     FROM unnest(%s::uuid[],%s::bigint[]) WITH ORDINALITY
                       AS source(memory_id,head_version,ordinal)
                   )
                   SELECT requested.memory_id,requested.head_version
                   FROM requested
                   JOIN armi.subjective_memory_revisions AS revision
                     ON revision.memory_id=requested.memory_id
                    AND revision.revision_no=requested.head_version
                   WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.subject_id=%s
                     AND revision.accessibility IN ('available','faded')
                   ORDER BY requested.ordinal""",
                (
                    [source.memory_id for source in sources],
                    [source.head_version for source in sources],
                    subject_id,
                ),
            )
        ).fetchall()
        return tuple(MemoryCandidateSourceRef(row[0], int(row[1])) for row in rows)

    async def lock_current_projection_head(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source: MemoryCandidateSourceRef,
    ) -> bool:
        await self._lock_memory(transaction, source.memory_id, shared=True)
        row = await (
            await transaction.execute(
                """SELECT revision.memory_id
                   FROM armi.subjective_memory_revisions AS revision
                   WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.memory_id=%s AND revision.revision_no=%s
                     AND revision.subject_id=%s
                     AND revision.accessibility IN ('available','faded')""",
                (
                    source.memory_id,
                    source.head_version,
                    subject_id,
                ),
            )
        ).fetchone()
        return row is not None

    async def projection_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID | None = None,
    ) -> tuple[MemoryProjectionSource, ...]:
        rows = await (
            await transaction.execute(
                """SELECT revision.subject_id,revision.memory_id,
                          revision.revision_no,revision.summary
                   FROM armi.subjective_memory_revisions AS revision
                   WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.accessibility IN ('available','faded')
                     AND (%s::uuid IS NULL OR revision.subject_id=%s)
                   ORDER BY revision.memory_id""",
                (subject_id, subject_id),
            )
        ).fetchall()
        return tuple(
            MemoryProjectionSource(row[0], row[1], int(row[2]), str(row[3]))
            for row in rows
        )

    async def load_source(
        self, transaction: PostgreSQLTransaction, memory_id: UUID
    ) -> MemoryProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT revision.subject_id,revision.memory_id,
                          revision.revision_no,revision.summary
                   FROM armi.subjective_memory_revisions AS revision
                   WHERE revision.is_current AND revision.tombstoned_at IS NULL
                     AND revision.memory_id=%s AND revision.accessibility IN ('available','faded')
                     """,
                (memory_id,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else MemoryProjectionSource(row[0], row[1], int(row[2]), str(row[3]))
        )


__all__ = ("PostgreSQLMemoryOwner",)
