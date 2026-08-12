"""PostgreSQL exact life-record and Creator memory projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_artifact_store.life_material_codec import (
    parse_life_material_artifact,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    CreatorLifeMaterialItem,
    CreatorLifeMaterialQueryViolation,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    LifeRecordActor,
    LifeRecordItem,
    LifeRecordKind,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryViolation,
)
from armi_kernel.contracts import Digest, Instant, OpaqueCursor
from armi_memory.api import (
    CreatorMemoryPage,
    CreatorMemoryTimeline,
    MemoryReadPort,
)
from armi_relationship.api import RelationshipReadPort
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
        "_memories",
        "_pool",
        "_pool_timeout_seconds",
        "_relationships",
        "_storage",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        cursor_key: bytes,
        data_root: Path,
        max_object_bytes: int,
        pool_timeout_seconds: int,
        memories: MemoryReadPort | None = None,
        relationships: RelationshipReadPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout_seconds = pool_timeout_seconds
        self._memories = memories
        self._relationships = relationships
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        )
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
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
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
                            CROSS JOIN query_input AS query
                            WHERE activity.subject_id = query.subject_id
                              AND (query.record_kind IS NULL OR query.record_kind = 'activity')
                              AND (query.query_text IS NULL OR left(revision.goal || CASE WHEN revision.progress_summary IS NULL THEN '' ELSE ' — ' || revision.progress_summary END, 4096) ILIKE '%%' || query.query_text || '%%')
                              AND (query.before_at IS NULL OR (revision.created_at, 'activity'::text, activity.activity_id) < (query.before_at, query.before_kind, query.before_id))
                            ORDER BY revision.created_at DESC, activity.activity_id DESC
                            LIMIT (SELECT branch_limit FROM query_input)
                            )
                            UNION ALL
                            (
                            SELECT experience.experience_id,
                                   'conversation'::text,
                                   experience.first_person_gist,
                                   experience.source_perspective,
                                   experience.accepted_at,
                                   NULL::boolean
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
                            UNION ALL
                            (
                            SELECT material.life_material_id,
                                   'material'::text,
                                   revision.title,
                                   'life_material_current'::text,
                                   revision.created_at,
                                   NULL::boolean
                            FROM armi.life_materials AS material
                            JOIN armi.life_material_revisions AS revision
                              ON revision.life_material_revision_id =
                                 material.current_revision_id
                            CROSS JOIN query_input AS query
                            WHERE material.subject_id = query.subject_id
                              AND material.deleted_at IS NULL
                              AND (query.record_kind IS NULL OR query.record_kind = 'material')
                              AND (query.query_text IS NULL OR revision.title ILIKE '%%' || query.query_text || '%%')
                              AND (query.before_at IS NULL OR (revision.created_at, 'material'::text, material.life_material_id) < (query.before_at, query.before_kind, query.before_id))
                              AND (
                                  query.actor = 'subject'
                                  OR revision.privacy_status = 'creator_visible'
                              )
                            ORDER BY revision.created_at DESC, material.life_material_id DESC
                            LIMIT (SELECT branch_limit FROM query_input)
                            )
                            UNION ALL
                            (
                            SELECT revision.component_revision_id,
                                   'self_change'::text,
                                   left(revision.semantic_payload::text, 4096),
                                   revision.origin_kind,
                                   revision.created_at,
                                   NULL::boolean
                            FROM armi.subject_component_revisions AS revision
                            CROSS JOIN query_input AS query
                            WHERE revision.subject_id = query.subject_id
                              AND revision.component_kind = 'self'
                              AND (query.record_kind IS NULL OR query.record_kind = 'self_change')
                              AND (query.query_text IS NULL OR revision.semantic_payload::text ILIKE '%%' || query.query_text || '%%')
                              AND (query.before_at IS NULL OR (revision.created_at, 'self_change'::text, revision.component_revision_id) < (query.before_at, query.before_kind, query.before_id))
                            ORDER BY revision.created_at DESC, revision.component_revision_id DESC
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
        except LifeRecordQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
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
            *relationship_rows,
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

    async def get_creator_visible(
        self,
        material_id: UUID,
    ) -> CreatorLifeMaterialItem | None:
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                try:
                    subject_id = await self._scope(connection, LifeRecordActor.CREATOR)
                except LifeRecordQueryViolation:
                    raise CreatorLifeMaterialQueryViolation(
                        "LIFE-MATERIAL-QUERY-NOT-AUTHORIZED"
                    ) from None
                row = await (
                    await connection.execute(
                        """
                        SELECT material.life_material_id,
                               material.current_revision_id,
                               material.material_kind,
                               material.head_version,
                               material.created_at,
                               material.updated_at,
                               revision.revision_no,
                               revision.title,
                               revision.metadata,
                               revision.material_status,
                               revision.privacy_status,
                               artifact.artifact_id,
                               artifact.content_digest,
                               artifact.byte_size,
                               artifact.media_type,
                               artifact.logical_kind,
                               artifact.privacy_scope,
                               artifact.integrity_status
                        FROM armi.life_materials AS material
                        JOIN armi.life_material_revisions AS revision
                          ON revision.life_material_revision_id =
                             material.current_revision_id
                        JOIN armi.artifacts AS artifact
                          ON artifact.artifact_id = revision.artifact_id
                        WHERE material.life_material_id = %s
                          AND material.subject_id = %s
                          AND material.deleted_at IS NULL
                          AND revision.privacy_status = 'creator_visible'
                        """,
                        (material_id, subject_id),
                    )
                ).fetchone()
        except CreatorLifeMaterialQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise CreatorLifeMaterialQueryViolation(
                "LIFE-MATERIAL-QUERY-UNAVAILABLE"
            ) from None
        if row is None:
            return None
        try:
            ref = ArtifactRef(
                ArtifactId(cast(UUID, row[11])),
                Digest(str(row[12])),
                int(row[13]),
                str(row[14]),
                str(row[15]),
                ArtifactPrivacyScope(str(row[16])),
                ArtifactIntegrityStatus(str(row[17])),
            )
            if (
                ref.media_type != "application/json"
                or ref.logical_kind != "life.material.content"
                or ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
                or ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            ):
                raise ValueError
            artifact_bytes = b""
            async with await self._storage.open_verified(ref) as stream:
                artifact_bytes = await stream.read()
            body = parse_life_material_artifact(artifact_bytes).decode(
                "utf-8", errors="strict"
            )
            return CreatorLifeMaterialItem(
                material_id=cast(UUID, row[0]),
                current_revision_id=cast(UUID, row[1]),
                material_kind=LifeMaterialKind(str(row[2])),
                revision_no=int(row[6]),
                head_version=int(row[3]),
                title=str(row[7]),
                body=body,
                metadata=_material_metadata(row[8]),
                material_status=LifeMaterialStatus(str(row[9])),
                privacy_status=LifeMaterialPrivacyStatus(str(row[10])),
                created_at=Instant(cast(datetime, row[4])),
                updated_at=Instant(cast(datetime, row[5])),
            )
        except ArtifactViolation, TypeError, ValueError, UnicodeError:
            raise CreatorLifeMaterialQueryViolation(
                "LIFE-MATERIAL-QUERY-UNAVAILABLE"
            ) from None

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


def _material_metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict:
        raise ValueError("life material metadata is invalid")
    raw = cast(dict[object, object], value)
    if any(type(key) is not str or type(item) is not str for key, item in raw.items()):
        raise ValueError("life material metadata is invalid")
    metadata = cast(dict[str, str], value)
    return tuple(sorted(metadata.items()))


__all__ = ("LifeRecordCursorCodec", "PostgreSQLLifeRecordQuery")
