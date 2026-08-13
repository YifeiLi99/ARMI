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

import rfc8785
from armi_activity.api import ActivityReadPort
from armi_kernel.application import (
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
)
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_material.api import MaterialReadPort
from armi_memory.api import (
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    MemoryReadPort,
)
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)
from armi_subject_state.api import SubjectStateReadPort


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


class PostgreSQLLifeRecordQuery:
    """Read current life facts without changing memory or subject state."""

    __slots__ = (
        "_activities",
        "_codec",
        "_creator_party_id",
        "_factory",
        "_materials",
        "_memories",
        "_relationships",
        "_subject_state",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        cursor_key: bytes,
        activities: ActivityReadPort,
        materials: MaterialReadPort,
        memories: MemoryReadPort | None = None,
        relationships: RelationshipReadPort,
        subject_state: SubjectStateReadPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._activities = activities
        self._factory = factory
        self._materials = materials
        self._memories = memories
        self._relationships = relationships
        self._subject_state = subject_state
        self._codec = LifeRecordCursorCodec(
            key=cursor_key,
            environment_id=environment_id,
            creator_party_id=creator_party_id,
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def query(self, request: LifeRecordQuery) -> LifeRecordPage:
        if request.record_kind is LifeRecordKind.MEMORY and self._memories is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
        memories = self._memories
        scope = {
            "projection_version": "life-record-query.v2",
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
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                subject_id = await self._scope(connection, request.actor)
                generation_row = await (
                    await connection.execute(
                        """
                        SELECT life_generation_id FROM armi.life_generations
                        WHERE subject_id = %s AND status = 'active'
                        """,
                        (subject_id,),
                    )
                ).fetchone()
                if generation_row is None:
                    raise LifeRecordQueryViolation("LIFE-QUERY-SCOPE")
                relationship_snapshots = await self._relationships.all_current(
                    connection,
                    subject_id=subject_id,
                    generation_id=generation_row[0],
                )
                activity_rows = (
                    await self._activities.life_record_branch(
                        connection,
                        subject_id=subject_id,
                        query_text=request.query_text,
                        before=None
                        if boundary is None
                        else (boundary[0].value, boundary[1], boundary[2]),
                        limit=request.limit + 1,
                    )
                    if request.record_kind in {None, LifeRecordKind.ACTIVITY}
                    else ()
                )
                rows = await (
                    await connection.execute(
                        """
                        WITH query_input AS (
                            SELECT %s::uuid AS subject_id,
                                   %s::text AS actor,
                                   %s::text AS record_kind,
                                   %s::text AS query_text,
                                   %s::timestamptz AS before_at,
                                   %s::text AS before_kind,
                                   %s::uuid AS before_id,
                                   %s::integer AS branch_limit
                        ), records AS (
                            (
                            SELECT experience.experience_id AS record_ref,
                                   'conversation'::text AS record_kind,
                                   experience.first_person_gist AS summary,
                                   experience.source_perspective AS source_kind,
                                   experience.accepted_at AS occurred_at,
                                   NULL::boolean AS naturally_recallable
                            FROM armi.accepted_experiences AS experience
                            CROSS JOIN query_input AS query
                            WHERE experience.subject_id = query.subject_id
                              AND (query.record_kind IS NULL OR query.record_kind = 'conversation')
                              AND (query.query_text IS NULL OR experience.first_person_gist ILIKE '%%' || query.query_text || '%%')
                              AND (query.before_at IS NULL OR (experience.accepted_at, 'conversation'::text, experience.experience_id) < (query.before_at, query.before_kind, query.before_id))
                              AND NOT EXISTS (
                                  SELECT 1 FROM armi.deletion_items AS deletion_item
                                  WHERE deletion_item.target_kind = 'experience'
                                    AND deletion_item.target_ref = experience.experience_id
                                    AND deletion_item.result_status IN ('completed', 'partial')
                              )
                            ORDER BY experience.accepted_at DESC, experience.experience_id DESC
                            LIMIT (SELECT branch_limit FROM query_input)
                            )
                        )
                        SELECT record_ref, record_kind, summary, source_kind,
                               occurred_at, naturally_recallable
                        FROM records
                        ORDER BY occurred_at DESC, record_kind DESC,
                                 record_ref DESC
                        """,
                        (
                            subject_id,
                            request.actor.value,
                            None
                            if request.record_kind is None
                            else request.record_kind.value,
                            request.query_text,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[1],
                            None if boundary is None else boundary[2],
                            request.limit + 1,
                        ),
                    )
                ).fetchall()
                rows = cast(
                    list[tuple[UUID, str, str, str, datetime, bool | None]],
                    rows,
                )
                subject_state_rows = (
                    await self._subject_state.life_record_branch(
                        connection,
                        subject_id=subject_id,
                        query_text=request.query_text,
                        before=None
                        if boundary is None
                        else (boundary[0].value, boundary[1], boundary[2]),
                        limit=request.limit + 1,
                    )
                    if request.record_kind in {None, LifeRecordKind.SELF_CHANGE}
                    else ()
                )
                memory_rows = (
                    await memories.life_record_branch(
                        connection,
                        subject_id=subject_id,
                        query_text=request.query_text,
                        before=None
                        if boundary is None
                        else (boundary[0].value, boundary[1], boundary[2]),
                        limit=request.limit + 1,
                    )
                    if memories is not None
                    and request.record_kind in {None, LifeRecordKind.MEMORY}
                    else ()
                )
                material_rows = (
                    await self._materials.life_record_branch(
                        connection,
                        subject_id=subject_id,
                        creator_visible_only=request.actor is LifeRecordActor.CREATOR,
                        query_text=request.query_text,
                        before=None
                        if boundary is None
                        else (boundary[0].value, boundary[1], boundary[2]),
                        limit=request.limit + 1,
                    )
                    if request.record_kind in {None, LifeRecordKind.MATERIAL}
                    else ()
                )
        except LifeRecordQueryViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
        relationship_rows: list[tuple[UUID, str, str, str, datetime, bool | None]] = [
            (
                snapshot.relationship_id,
                "relationship",
                snapshot.revision.interpretation,
                "relationship_current",
                snapshot.revision.occurred_at,
                None,
            )
            for snapshot in relationship_snapshots
            if request.record_kind in {None, LifeRecordKind.RELATIONSHIP}
            and (
                request.query_text is None
                or request.query_text.casefold()
                in snapshot.revision.interpretation.casefold()
            )
            and (
                boundary is None
                or (
                    snapshot.revision.occurred_at,
                    "relationship",
                    snapshot.relationship_id,
                )
                < (boundary[0].value, boundary[1], boundary[2])
            )
        ]
        combined_rows: list[tuple[UUID, str, str, str, datetime, bool | None]] = [
            *rows,
            *(
                (
                    item.revision_id,
                    "self_change",
                    item.summary,
                    item.source_kind,
                    item.occurred_at,
                    None,
                )
                for item in subject_state_rows
            ),
            *(
                (
                    item.activity_id,
                    "activity",
                    item.summary,
                    "activity_current",
                    item.occurred_at,
                    None,
                )
                for item in activity_rows
            ),
            *relationship_rows,
            *(
                (
                    item.material_id,
                    "material",
                    item.title,
                    "life_material_current",
                    item.occurred_at,
                    None,
                )
                for item in material_rows
            ),
            *(
                (
                    item.memory_id,
                    "memory",
                    item.summary,
                    item.source_kind,
                    item.occurred_at,
                    item.naturally_recallable,
                )
                for item in memory_rows
            ),
        ]
        rows = sorted(
            combined_rows,
            key=lambda row: (row[4], row[1], row[0]),
            reverse=True,
        )
        visible = rows[: request.limit]
        next_cursor = None
        if len(rows) > request.limit and visible:
            oldest = visible[-1]
            next_cursor = self._codec.encode(
                scope=scope,
                boundary={
                    "before_at": Instant(oldest[4]).to_wire(),
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
                    occurred_at=Instant(row[4]),
                    naturally_recallable=row[5],
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
        if self._memories is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
        return await self._memories.list_current(
            limit=limit, query_text=query_text, cursor=cursor
        )

    async def timeline(
        self,
        memory_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> CreatorMemoryTimeline:
        if self._memories is None:
            raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
        return await self._memories.timeline(memory_id, limit=limit, cursor=cursor)

    async def _scope(
        self,
        connection: PostgreSQLTransaction,
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


__all__ = ("LifeRecordCursorCodec", "PostgreSQLLifeRecordQuery")
