"""Read-only PostgreSQL projection for Creator-visible other-human records."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    OtherHumanPartyRecord,
    OtherHumanPartyRecordPage,
    OtherHumanRecordDirection,
    OtherHumanRecordViolation,
    OtherHumanSceneRecord,
    OtherHumanSceneRecordPage,
    OtherHumanTimelineRecord,
    OtherHumanTimelineRecordPage,
)
from armi_kernel.contracts import Digest, Instant, OpaqueCursor
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore

from .role_policy import physical_role_name

_SEARCH_PATH = "pg_catalog, armi"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    decoded = base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )
    if _b64encode(decoded) != value:
        raise ValueError
    return decoded


class OtherHumanRecordCursorCodec:
    __slots__ = ("_environment_id", "_key")

    def __init__(self, *, key: bytes, environment_id: UUID) -> None:
        if len(key) != hashlib.sha256().digest_size or environment_id.version != 7:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR")
        self._key = key
        self._environment_id = environment_id

    def encode(
        self, resource: str, scope: str, boundary: dict[str, str]
    ) -> OpaqueCursor:
        payload = {
            "contract_version": "1.0",
            "projection_version": "other-human-record.v1",
            "environment_id": str(self._environment_id),
            "resource": resource,
            "scope": scope,
            **boundary,
        }
        encoded = _b64encode(rfc8785.dumps(cast(Any, payload)))
        signature = _b64encode(
            hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return OpaqueCursor(f"v1.{encoded}.{signature}")

    def decode(
        self, cursor: OpaqueCursor, resource: str, scope: str, keys: set[str]
    ) -> dict[str, str]:
        try:
            prefix, encoded, signature = cursor.value.split(".", 2)
            expected = hmac.new(
                self._key, encoded.encode("ascii"), hashlib.sha256
            ).digest()
            raw = _b64decode(encoded)
            payload = cast(dict[str, object], json.loads(raw))
            if (
                prefix != "v1"
                or not hmac.compare_digest(_b64decode(signature), expected)
                or rfc8785.dumps(cast(Any, payload)) != raw
                or payload.get("contract_version") != "1.0"
                or payload.get("projection_version") != "other-human-record.v1"
                or payload.get("environment_id") != str(self._environment_id)
                or payload.get("resource") != resource
                or payload.get("scope") != scope
                or set(payload)
                != {
                    "contract_version",
                    "projection_version",
                    "environment_id",
                    "resource",
                    "scope",
                    *keys,
                }
                or any(type(payload.get(key)) is not str for key in keys)
            ):
                raise ValueError
        except UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR") from None
        return {key: cast(str, payload[key]) for key in keys}


async def _configure(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLOtherHumanRecordQuery:
    __slots__ = ("_codec", "_expected_role", "_pool", "_pool_timeout", "_storage")

    def __init__(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        cursor_key: bytes,
        data_root: Path,
        max_object_bytes: int,
        pool_timeout_seconds: int,
    ) -> None:
        self._codec = OtherHumanRecordCursorCodec(
            key=cursor_key, environment_id=environment_id
        )
        self._expected_role = physical_role_name(environment_id, "runtime")
        self._pool_timeout = pool_timeout_seconds
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        )

        async def check(connection: psycopg.AsyncConnection[tuple[Any, ...]]) -> None:
            row = await (
                await connection.execute(
                    "SELECT session_user, current_user, current_setting('search_path')"
                )
            ).fetchone()
            if row != (self._expected_role, self._expected_role, _SEARCH_PATH):
                raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-other-human-record-query",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._pool.close()

    async def list_parties(
        self, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanPartyRecordPage:
        self._check_limit(limit)
        boundary: UUID | None = None
        if cursor is not None:
            boundary = self._uuid(
                self._codec.decode(cursor, "parties", "all", {"before_id"})["before_id"]
            )
        clause = "" if boundary is None else "AND party.party_id < %s"
        parameters: tuple[object, ...] = (
            (limit + 1,) if boundary is None else (boundary, limit + 1)
        )
        rows = await self._fetchall(
            f"""
            SELECT party.party_id, party.declared_identity_key, party.display_label,
                   count(DISTINCT scene.scene_id), count(item.timeline_item_id),
                   max(item.occurred_at)
            FROM armi.parties AS party
            JOIN armi.interaction_scenes AS scene
              ON scene.primary_party_id = party.party_id
             AND scene.scene_kind = 'other_human_dialogue'
            JOIN armi.scene_timeline_items AS item
              ON item.scene_id = scene.scene_id
             AND item.source_kind IN ('other_human_input', 'other_human_response')
            LEFT JOIN armi.external_evidence AS evidence
              ON item.source_kind = 'other_human_input'
             AND evidence.interaction_id = item.source_ref
            LEFT JOIN armi.effects AS effect
              ON item.source_kind = 'other_human_response'
             AND effect.effect_id = item.source_ref
            JOIN armi.artifacts AS artifact
              ON artifact.artifact_id = COALESCE(evidence.artifact_id, effect.payload_artifact_id)
             AND artifact.integrity_status = 'verified'
             AND artifact.privacy_scope = 'private'
             AND artifact.retention_status = 'retained'
            WHERE party.party_kind = 'other_human'
              AND NOT EXISTS (
                  SELECT 1 FROM armi.deletion_orders AS deletion_order
                  WHERE deletion_order.requester_party_id = party.party_id
                    AND deletion_order.order_kind = 'delete_related'
                    AND deletion_order.status = 'effective'
              ) {clause}
            GROUP BY party.party_id, party.declared_identity_key, party.display_label
            ORDER BY party.party_id DESC LIMIT %s
            """,
            parameters,
        )
        more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(self._party(row) for row in visible)
        next_cursor = (
            self._codec.encode("parties", "all", {"before_id": str(visible[-1][0])})
            if more
            else None
        )
        return OtherHumanPartyRecordPage(items, next_cursor)

    async def list_scenes(
        self, party_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanSceneRecordPage:
        self._check_limit(limit)
        party_id = self._valid_uuid(party_id)
        party_row = await self._fetchone(
            """
            SELECT party.party_id, party.declared_identity_key, party.display_label,
                   count(DISTINCT scene.scene_id), count(item.timeline_item_id),
                   max(item.occurred_at)
            FROM armi.parties AS party
            JOIN armi.interaction_scenes AS scene
              ON scene.primary_party_id = party.party_id
             AND scene.scene_kind = 'other_human_dialogue'
            JOIN armi.scene_timeline_items AS item ON item.scene_id = scene.scene_id
             AND item.source_kind IN ('other_human_input', 'other_human_response')
            LEFT JOIN armi.external_evidence AS evidence
              ON item.source_kind = 'other_human_input'
             AND evidence.interaction_id = item.source_ref
            LEFT JOIN armi.effects AS effect
              ON item.source_kind = 'other_human_response'
             AND effect.effect_id = item.source_ref
            JOIN armi.artifacts AS artifact
              ON artifact.artifact_id = COALESCE(evidence.artifact_id, effect.payload_artifact_id)
             AND artifact.integrity_status = 'verified'
             AND artifact.privacy_scope = 'private'
             AND artifact.retention_status = 'retained'
            WHERE party.party_id = %s AND party.party_kind = 'other_human'
              AND NOT EXISTS (
                  SELECT 1 FROM armi.deletion_orders AS deletion_order
                  WHERE deletion_order.requester_party_id = party.party_id
                    AND deletion_order.order_kind = 'delete_related'
                    AND deletion_order.status = 'effective'
              )
            GROUP BY party.party_id, party.declared_identity_key, party.display_label
            """,
            (party_id,),
        )
        if party_row is None:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-NOT-VISIBLE")
        boundary: UUID | None = None
        scope = str(party_id)
        if cursor is not None:
            boundary = self._uuid(
                self._codec.decode(cursor, "scenes", scope, {"before_id"})["before_id"]
            )
        clause = "" if boundary is None else "AND scene.scene_id < %s"
        parameters: tuple[object, ...] = (
            (party_id, limit + 1)
            if boundary is None
            else (party_id, boundary, limit + 1)
        )
        rows = await self._fetchall(
            f"""
            SELECT scene.scene_id, scene.scene_key, scene.current_status,
                   count(item.timeline_item_id), max(item.occurred_at)
            FROM armi.interaction_scenes AS scene
            JOIN armi.scene_timeline_items AS item ON item.scene_id = scene.scene_id
             AND item.source_kind IN ('other_human_input', 'other_human_response')
            LEFT JOIN armi.external_evidence AS evidence
              ON item.source_kind = 'other_human_input'
             AND evidence.interaction_id = item.source_ref
            LEFT JOIN armi.effects AS effect
              ON item.source_kind = 'other_human_response'
             AND effect.effect_id = item.source_ref
            JOIN armi.artifacts AS artifact
              ON artifact.artifact_id = COALESCE(evidence.artifact_id, effect.payload_artifact_id)
             AND artifact.integrity_status = 'verified'
             AND artifact.privacy_scope = 'private'
             AND artifact.retention_status = 'retained'
            WHERE scene.primary_party_id = %s
              AND scene.scene_kind = 'other_human_dialogue' {clause}
              AND NOT EXISTS (
                  SELECT 1 FROM armi.deletion_orders AS deletion_order
                  WHERE deletion_order.requester_party_id = scene.primary_party_id
                    AND deletion_order.order_kind = 'delete_related'
                    AND deletion_order.status = 'effective'
              )
            GROUP BY scene.scene_id, scene.scene_key, scene.current_status
            ORDER BY scene.scene_id DESC LIMIT %s
            """,
            parameters,
        )
        more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            OtherHumanSceneRecord(
                cast(UUID, row[0]), str(row[1]), str(row[2]), int(row[3]), row[4]
            )
            for row in visible
        )
        next_cursor = (
            self._codec.encode("scenes", scope, {"before_id": str(visible[-1][0])})
            if more
            else None
        )
        return OtherHumanSceneRecordPage(self._party(party_row), items, next_cursor)

    async def timeline(
        self,
        party_id: UUID,
        scene_id: UUID,
        *,
        limit: int,
        cursor: OpaqueCursor | None = None,
    ) -> OtherHumanTimelineRecordPage:
        self._check_limit(limit)
        party_id, scene_id = self._valid_uuid(party_id), self._valid_uuid(scene_id)
        visible = await self._fetchone(
            """
            SELECT 1
            FROM armi.interaction_scenes AS scene
            JOIN armi.parties AS party
              ON party.party_id = scene.primary_party_id
             AND party.party_kind = 'other_human'
            WHERE scene.scene_id = %s AND scene.primary_party_id = %s
              AND scene.scene_kind = 'other_human_dialogue'
              AND NOT EXISTS (
                  SELECT 1 FROM armi.deletion_orders AS deletion_order
                  WHERE deletion_order.requester_party_id = scene.primary_party_id
                    AND deletion_order.order_kind = 'delete_related'
                    AND deletion_order.status = 'effective'
              )
            """,
            (scene_id, party_id),
        )
        if visible is None:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-NOT-VISIBLE")
        scope = f"{party_id}:{scene_id}"
        boundary: tuple[Instant, UUID] | None = None
        if cursor is not None:
            decoded = self._codec.decode(
                cursor, "timeline", scope, {"before_at", "before_id"}
            )
            try:
                boundary = (
                    Instant.from_wire(decoded["before_at"]),
                    self._uuid(decoded["before_id"]),
                )
            except ValueError:
                raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR") from None
        clause = (
            ""
            if boundary is None
            else "AND (item.occurred_at, item.timeline_item_id) < (%s, %s)"
        )
        parameters: tuple[object, ...] = (
            (party_id, scene_id, limit + 1)
            if boundary is None
            else (party_id, scene_id, boundary[0].value, boundary[1], limit + 1)
        )
        rows = await self._fetchall(
            f"""
            SELECT item.timeline_item_id, item.source_kind, item.source_ref,
                   item.result_status, item.occurred_at,
                   artifact.artifact_id, artifact.content_digest,
                   artifact.byte_size, artifact.media_type, artifact.logical_kind,
                   artifact.privacy_scope, artifact.integrity_status
            FROM armi.scene_timeline_items AS item
            JOIN armi.interaction_scenes AS scene ON scene.scene_id = item.scene_id
            LEFT JOIN armi.external_evidence AS evidence
              ON item.source_kind = 'other_human_input'
             AND evidence.interaction_id = item.source_ref
            LEFT JOIN armi.effects AS effect
              ON item.source_kind = 'other_human_response'
             AND effect.effect_id = item.source_ref
            JOIN armi.artifacts AS artifact
              ON artifact.artifact_id = COALESCE(evidence.artifact_id, effect.payload_artifact_id)
             AND artifact.integrity_status = 'verified'
             AND artifact.privacy_scope = 'private'
             AND artifact.retention_status = 'retained'
            WHERE scene.primary_party_id = %s AND scene.scene_id = %s
              AND scene.scene_kind = 'other_human_dialogue'
              AND item.source_kind IN ('other_human_input', 'other_human_response')
              AND NOT EXISTS (
                  SELECT 1 FROM armi.deletion_orders AS deletion_order
                  WHERE deletion_order.requester_party_id = scene.primary_party_id
                    AND deletion_order.order_kind = 'delete_related'
                    AND deletion_order.status = 'effective'
              )
              {clause}
            ORDER BY item.occurred_at DESC, item.timeline_item_id DESC LIMIT %s
            """,
            parameters,
        )
        more = len(rows) > limit
        visible = rows[:limit]
        items = tuple([await self._timeline_item(row) for row in visible])
        next_cursor = (
            self._codec.encode(
                "timeline",
                scope,
                {
                    "before_at": Instant(cast(datetime, visible[-1][4])).to_wire(),
                    "before_id": str(visible[-1][0]),
                },
            )
            if more
            else None
        )
        return OtherHumanTimelineRecordPage(party_id, scene_id, items, next_cursor)

    async def _timeline_item(self, row: tuple[Any, ...]) -> OtherHumanTimelineRecord:
        try:
            ref = ArtifactRef(
                ArtifactId(cast(UUID, row[5])),
                Digest(str(row[6])),
                int(row[7]),
                str(row[8]),
                str(row[9]),
                ArtifactPrivacyScope(str(row[10])),
                ArtifactIntegrityStatus(str(row[11])),
            )
            if ref.media_type != "text/plain":
                raise ValueError
            text = ""
            async with await self._storage.open_verified(ref) as stream:
                text = (await stream.read()).decode("utf-8", errors="strict")
            return OtherHumanTimelineRecord(
                cast(UUID, row[0]),
                cast(UUID, row[2]),
                OtherHumanRecordDirection(
                    "received" if row[1] == "other_human_input" else "sent"
                ),
                str(row[3]),
                text,
                cast(datetime, row[4]),
            )
        except ArtifactViolation, ValueError, UnicodeError, OSError:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None

    async def _fetchall(
        self, statement: str, parameters: tuple[object, ...]
    ) -> list[tuple[Any, ...]]:
        try:
            async with (
                self._pool.connection(timeout=float(self._pool_timeout)) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                return await (
                    await connection.execute(
                        sql.SQL(cast(LiteralString, statement)), parameters
                    )
                ).fetchall()
        except psycopg.Error, PoolTimeout:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None

    async def _fetchone(
        self, statement: str, parameters: tuple[object, ...]
    ) -> tuple[Any, ...] | None:
        rows = await self._fetchall(statement, parameters)
        return rows[0] if rows else None

    @staticmethod
    def _party(row: tuple[Any, ...]) -> OtherHumanPartyRecord:
        return OtherHumanPartyRecord(
            cast(UUID, row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            int(row[4]),
            row[5],
        )

    @staticmethod
    def _check_limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-LIMIT")

    @staticmethod
    def _uuid(value: str) -> UUID:
        try:
            parsed = UUID(value)
        except ValueError:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR") from None
        return PostgreSQLOtherHumanRecordQuery._valid_uuid(parsed)

    @staticmethod
    def _valid_uuid(value: UUID) -> UUID:
        if type(value) is not UUID or value.version != 7:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-SCOPE")
        return value


__all__ = ("OtherHumanRecordCursorCodec", "PostgreSQLOtherHumanRecordQuery")
