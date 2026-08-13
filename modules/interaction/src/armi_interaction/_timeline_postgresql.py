"""Read-only PostgreSQL gateway for the Creator-visible scene timeline."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_data_rights.api import DataRightsVisibilityPort
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditResultStatus,
)
from armi_kernel.contracts import Digest, Instant, OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._scene_contract import (
    PROJECTION_VERSION,
    SceneQueryViolation,
    SceneTimelineCodexTaskProjectionPort,
    SceneTimelineItem,
    SceneTimelinePage,
    SceneTimelineQuery,
    TimelineItemId,
)
from .api import InteractionCreatorTimelineProjectionPort


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


class SceneTimelineCursorCodec:
    """Sign stable pagination boundaries scoped to one visible scene."""

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
            raise SceneQueryViolation("SCENE-CURSOR-INVALID")
        self._key = key
        self._environment_id = environment_id
        self._creator_party_id = creator_party_id

    def encode(
        self,
        *,
        scene_id: UUID,
        scene_key: str,
        limit: int,
        before_at: Instant,
        before_id: UUID,
    ) -> OpaqueCursor:
        payload = {
            "contract_version": "1.0",
            "projection_version": PROJECTION_VERSION,
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            "scene_id": str(scene_id),
            "scene_key": scene_key,
            "limit": limit,
            "direction": "older",
            "before_at": before_at.to_wire(),
            "before_id": str(before_id),
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
        scene_id: UUID,
        scene_key: str,
        limit: int,
    ) -> tuple[Instant, UUID]:
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
        except (
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
            TypeError,
        ):
            raise SceneQueryViolation("SCENE-CURSOR-INVALID") from None
        if (
            payload.get("contract_version") != "1.0"
            or payload.get("projection_version") != PROJECTION_VERSION
        ):
            raise SceneQueryViolation("SCENE-CURSOR-STALE")
        expected_scope: dict[str, object] = {
            "environment_id": str(self._environment_id),
            "creator_party_id": str(self._creator_party_id),
            "scene_id": str(scene_id),
            "scene_key": scene_key,
            "limit": limit,
            "direction": "older",
        }
        if any(payload.get(key) != value for key, value in expected_scope.items()):
            raise SceneQueryViolation("SCENE-CURSOR-INVALID")
        if set(payload) != {
            "contract_version",
            "projection_version",
            *expected_scope,
            "before_at",
            "before_id",
        }:
            raise SceneQueryViolation("SCENE-CURSOR-INVALID")
        try:
            before_at = Instant.from_wire(payload["before_at"])
            before_id = UUID(cast(str, payload["before_id"]))
        except KeyError, TypeError, ValueError:
            raise SceneQueryViolation("SCENE-CURSOR-INVALID") from None
        if before_id.version != 7 or str(before_id) != payload["before_id"]:
            raise SceneQueryViolation("SCENE-CURSOR-INVALID")
        return before_at, before_id


class PostgreSQLSceneTimelineQuery:
    """Query one Creator-visible scene using a dedicated read-only pool."""

    __slots__ = (
        "_codec",
        "_codex_tasks",
        "_creator_party_id",
        "_factory",
        "_projections",
        "_storage",
        "_visibility",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        environment_id: UUID,
        creator_party_id: UUID,
        cursor_key: bytes,
        storage: ContentAddressedArtifactStore,
        codex_tasks: SceneTimelineCodexTaskProjectionPort,
        visibility: DataRightsVisibilityPort,
        projections: InteractionCreatorTimelineProjectionPort,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._factory = factory
        self._storage = storage
        self._codex_tasks = codex_tasks
        self._visibility = visibility
        self._projections = projections
        self._codec = SceneTimelineCursorCodec(
            key=cursor_key,
            environment_id=environment_id,
            creator_party_id=creator_party_id,
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def query(self, request: SceneTimelineQuery) -> SceneTimelinePage:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                restrictions = await self._visibility.party_restrictions(
                    connection, self._creator_party_id
                )
                if "delete_related" in restrictions:
                    raise SceneQueryViolation("SCENE-NOT-VISIBLE")
                scene_rows = await (
                    await connection.execute(
                        """
                        SELECT scene.scene_id
                        FROM armi.interaction_scenes AS scene
                        JOIN armi.parties AS creator
                          ON creator.party_id = scene.primary_party_id
                         AND creator.party_kind = 'creator'
                         AND creator.creator_role = 'unique_primary_creator'
                         AND creator.status = 'active'
                        WHERE scene.scene_key = %s
                          AND scene.scene_kind = 'creator_dialogue'
                          AND scene.audience_scope = 'creator'
                          AND creator.party_id = %s
                        """,
                        (request.scene_key.value, self._creator_party_id),
                    )
                ).fetchall()
                if len(scene_rows) != 1 or not isinstance(
                    cast(object, scene_rows[0][0]), UUID
                ):
                    raise SceneQueryViolation("SCENE-NOT-VISIBLE")
                scene_id = scene_rows[0][0]
                boundary: tuple[Instant, UUID] | None = None
                if request.cursor is not None:
                    boundary = self._codec.decode(
                        request.cursor,
                        scene_id=scene_id,
                        scene_key=request.scene_key.value,
                        limit=request.limit,
                    )
                rows = await (
                    await connection.execute(
                        """
                        SELECT item.timeline_item_id,
                               CASE WHEN item.source_kind = 'party_response'
                                    THEN 'creator_response' ELSE item.source_kind END,
                               item.source_ref, item.result_status, item.occurred_at,
                               interaction.purpose, interaction.content_digest
                        FROM armi.scene_timeline_items AS item
                        LEFT JOIN armi.party_input_interactions AS interaction
                          ON item.source_kind = 'creator_input'
                         AND interaction.interaction_id = item.source_ref
                        WHERE item.scene_id = %s
                          AND (%s::timestamptz IS NULL OR
                               (item.occurred_at, item.timeline_item_id)
                                   < (%s::timestamptz, %s::uuid))
                        ORDER BY item.occurred_at DESC, item.timeline_item_id DESC
                        LIMIT %s
                        """,
                        (
                            scene_id,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[0].value,
                            None if boundary is None else boundary[1],
                            request.limit + 1,
                        ),
                    )
                ).fetchall()
                visible = rows[: request.limit]
                operations: dict[UUID, UUID] = {}
                effects: dict[UUID, UUID] = {}
                messages: dict[UUID, str] = {}
                for row in visible:
                    item_id = cast(UUID, row[0])
                    source_kind = str(row[1])
                    source_ref = cast(UUID, row[2])
                    if source_kind == "creator_input":
                        projection = await self._projections.creator_input(
                            unit_of_work,
                            interaction_id=source_ref,
                            purpose=str(row[5]),
                            content_digest=Digest(str(row[6])),
                        )
                        operations[item_id] = projection.operation_ref
                        messages[item_id] = await self._read_message(
                            projection.artifact, projection.purpose
                        )
                    elif source_kind == "subject_commit":
                        operations[item_id] = await self._projections.subject_commit(
                            connection,
                            subject_commit_id=source_ref,
                            context_party_id=self._creator_party_id,
                        )
                    elif source_kind == "creator_response":
                        effects[item_id] = source_ref
        except SceneQueryViolation:
            raise
        except RuntimeTransactionFailure as error:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE") from error

        items = tuple(
            SceneTimelineItem(
                timeline_item_id=TimelineItemId(row[0]),
                source_kind=str(row[1]),
                source_ref=row[2],
                status=AuditResultStatus(str(row[3])),
                occurred_at=Instant(cast(datetime, row[4])),
                operation_ref=operations.get(cast(UUID, row[0])),
                effect_ref=effects.get(cast(UUID, row[0])),
                message=messages.get(cast(UUID, row[0])),
            )
            for row in reversed(visible)
        )
        next_cursor = None
        if len(rows) > request.limit and visible:
            oldest = visible[-1]
            next_cursor = self._codec.encode(
                scene_id=scene_id,
                scene_key=request.scene_key.value,
                limit=request.limit,
                before_at=Instant(cast(datetime, oldest[4])),
                before_id=oldest[0],
            )
        return SceneTimelinePage(
            scene_key=request.scene_key,
            items=items,
            next_cursor=next_cursor,
        )

    async def _read_message(self, ref: ArtifactRef, purpose: str) -> str:
        if ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        try:
            value = b""
            async with await self._storage.open_verified(ref) as stream:
                value = await stream.read()
            if purpose == "creator_message":
                if (
                    ref.media_type != "text/plain"
                    or ref.logical_kind != "creator.input.text"
                    or ref.privacy_scope is not ArtifactPrivacyScope.CREATOR_VISIBLE
                ):
                    raise ValueError
                message = value.decode("utf-8", errors="strict")
            elif purpose == "codex_task_request":
                message = self._codex_tasks.objective(artifact=ref, content=value)
            else:
                raise ValueError
            if (
                not value
                or len(value) > 65536
                or "\x00" in message
                or not any(not character.isspace() for character in message)
            ):
                raise ValueError
            return message
        except ArtifactViolation, OSError, TypeError, UnicodeError, ValueError:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE") from None


__all__ = ("PostgreSQLSceneTimelineQuery", "SceneTimelineCursorCodec")
