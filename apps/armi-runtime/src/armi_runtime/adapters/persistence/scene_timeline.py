"""Read-only PostgreSQL gateway for the Creator-visible scene timeline."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import psycopg
import rfc8785
from armi_kernel.application import (
    PROJECTION_VERSION,
    AuditResultStatus,
    SceneQueryViolation,
    SceneTimelineItem,
    SceneTimelinePage,
    SceneTimelineQuery,
    TimelineItemId,
)
from armi_kernel.contracts import Instant, OpaqueCursor
from psycopg.pq import TransactionStatus
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .role_policy import physical_role_name

_SEARCH_PATH = "pg_catalog, armi"


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


async def _configure(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    await connection.set_autocommit(True)
    await connection.execute("SET search_path TO pg_catalog, armi")


async def _reset(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        await connection.rollback()
    await connection.execute("RESET ROLE")
    await connection.execute("RESET ALL")
    await connection.execute("SET search_path TO pg_catalog, armi")


class PostgreSQLSceneTimelineQuery:
    """Query one Creator-visible scene using a dedicated read-only pool."""

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
        self._codec = SceneTimelineCursorCodec(
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
                raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")

        self._pool = AsyncConnectionPool[psycopg.AsyncConnection[tuple[Any, ...]]](
            conninfo,
            min_size=1,
            max_size=1,
            open=False,
            configure=_configure,
            check=check,
            reset=_reset,
            timeout=float(pool_timeout_seconds),
            name="armi-scene-timeline-query",
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
        except psycopg.Error, PoolTimeout:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._pool.close()

    async def query(self, request: SceneTimelineQuery) -> SceneTimelinePage:
        if request.scene_key.value != "default":
            raise SceneQueryViolation("SCENE-NOT-VISIBLE")
        try:
            async with (
                self._pool.connection(
                    timeout=float(self._pool_timeout_seconds)
                ) as connection,
                connection.transaction(),
            ):
                await connection.execute("SET TRANSACTION READ ONLY")
                scene_rows = await (
                    await connection.execute(
                        """
                        SELECT scene.scene_id
                        FROM armi.interaction_scenes AS scene
                        JOIN armi.subjects AS subject
                          ON subject.subject_id = scene.subject_id
                         AND subject.singleton_key = 1
                        JOIN armi.parties AS creator
                          ON creator.party_id = scene.primary_party_id
                         AND creator.party_kind = 'creator'
                         AND creator.creator_role = 'unique_primary_creator'
                         AND creator.status = 'active'
                        WHERE scene.scene_key = %s
                          AND scene.scene_kind = 'creator_dialogue'
                          AND scene.audience_scope = 'creator'
                          AND scene.current_status = 'open'
                          AND scene.closed_at IS NULL
                          AND creator.party_id = %s
                        """,
                        (request.scene_key.value, self._creator_party_id),
                    )
                ).fetchall()
                if len(scene_rows) != 1 or not isinstance(scene_rows[0][0], UUID):
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
                if boundary is None:
                    rows = await (
                        await connection.execute(
                            """
                            SELECT
                                item.timeline_item_id,
                                item.source_kind,
                                item.source_ref,
                                item.result_status,
                                item.occurred_at,
                                COALESCE(
                                    opportunity.root_opportunity_id,
                                    commit_opportunity.root_opportunity_id
                                )
                            FROM armi.scene_timeline_items AS item
                            LEFT JOIN armi.creator_input_interactions AS interaction
                              ON item.source_kind = 'creator_input'
                             AND interaction.creator_interaction_id = item.source_ref
                             AND interaction.scene_id = item.scene_id
                             AND interaction.creator_party_id = %s
                            LEFT JOIN armi.external_evidence AS evidence
                              ON evidence.creator_interaction_id =
                                 interaction.creator_interaction_id
                             AND evidence.subject_id = interaction.subject_id
                             AND evidence.scene_id = interaction.scene_id
                             AND evidence.creator_party_id =
                                 interaction.creator_party_id
                            LEFT JOIN armi.opportunities AS opportunity
                              ON opportunity.evidence_id = evidence.evidence_id
                             AND opportunity.subject_id = evidence.subject_id
                             AND opportunity.scene_id = evidence.scene_id
                             AND opportunity.creator_party_id =
                                 evidence.creator_party_id
                             AND opportunity.reconsideration_no = 0
                            LEFT JOIN armi.subject_commits AS subject_commit
                              ON item.source_kind = 'subject_commit'
                             AND subject_commit.subject_commit_id = item.source_ref
                            LEFT JOIN armi.cognitive_episodes AS commit_episode
                              ON commit_episode.cognitive_episode_id =
                                 subject_commit.cognitive_episode_id
                            LEFT JOIN armi.opportunities AS commit_opportunity
                              ON commit_opportunity.opportunity_id =
                                 commit_episode.opportunity_id
                             AND commit_opportunity.creator_party_id = %s
                            WHERE item.scene_id = %s
                            ORDER BY item.occurred_at DESC,
                                     item.timeline_item_id DESC
                            LIMIT %s
                            """,
                            (
                                self._creator_party_id,
                                self._creator_party_id,
                                scene_id,
                                request.limit + 1,
                            ),
                        )
                    ).fetchall()
                else:
                    rows = await (
                        await connection.execute(
                            """
                            SELECT
                                item.timeline_item_id,
                                item.source_kind,
                                item.source_ref,
                                item.result_status,
                                item.occurred_at,
                                COALESCE(
                                    opportunity.root_opportunity_id,
                                    commit_opportunity.root_opportunity_id
                                )
                            FROM armi.scene_timeline_items AS item
                            LEFT JOIN armi.creator_input_interactions AS interaction
                              ON item.source_kind = 'creator_input'
                             AND interaction.creator_interaction_id = item.source_ref
                             AND interaction.scene_id = item.scene_id
                             AND interaction.creator_party_id = %s
                            LEFT JOIN armi.external_evidence AS evidence
                              ON evidence.creator_interaction_id =
                                 interaction.creator_interaction_id
                             AND evidence.subject_id = interaction.subject_id
                             AND evidence.scene_id = interaction.scene_id
                             AND evidence.creator_party_id =
                                 interaction.creator_party_id
                            LEFT JOIN armi.opportunities AS opportunity
                              ON opportunity.evidence_id = evidence.evidence_id
                             AND opportunity.subject_id = evidence.subject_id
                             AND opportunity.scene_id = evidence.scene_id
                             AND opportunity.creator_party_id =
                                 evidence.creator_party_id
                             AND opportunity.reconsideration_no = 0
                            LEFT JOIN armi.subject_commits AS subject_commit
                              ON item.source_kind = 'subject_commit'
                             AND subject_commit.subject_commit_id = item.source_ref
                            LEFT JOIN armi.cognitive_episodes AS commit_episode
                              ON commit_episode.cognitive_episode_id =
                                 subject_commit.cognitive_episode_id
                            LEFT JOIN armi.opportunities AS commit_opportunity
                              ON commit_opportunity.opportunity_id =
                                 commit_episode.opportunity_id
                             AND commit_opportunity.creator_party_id = %s
                            WHERE item.scene_id = %s
                              AND (item.occurred_at, item.timeline_item_id)
                                  < (%s, %s)
                            ORDER BY item.occurred_at DESC,
                                     item.timeline_item_id DESC
                            LIMIT %s
                            """,
                            (
                                self._creator_party_id,
                                self._creator_party_id,
                                scene_id,
                                boundary[0].value,
                                boundary[1],
                                request.limit + 1,
                            ),
                        )
                    ).fetchall()
        except SceneQueryViolation:
            raise
        except psycopg.Error, PoolTimeout:
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE") from None

        visible = rows[: request.limit]
        if any(
            (str(row[1]) in {"creator_input", "subject_commit"})
            != isinstance(row[5], UUID)
            for row in visible
        ):
            raise SceneQueryViolation("SCENE-QUERY-UNAVAILABLE")
        items = tuple(
            SceneTimelineItem(
                timeline_item_id=TimelineItemId(row[0]),
                source_kind=str(row[1]),
                source_ref=row[2],
                status=AuditResultStatus(str(row[3])),
                occurred_at=Instant(cast(datetime, row[4])),
                operation_ref=cast(UUID | None, row[5]),
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


__all__ = ("PostgreSQLSceneTimelineQuery", "SceneTimelineCursorCodec")
