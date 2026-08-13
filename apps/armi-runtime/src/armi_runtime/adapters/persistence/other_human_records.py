"""Read-only PostgreSQL projection for Creator-visible other-human records."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_data_rights.api import DataRightsVisibilityPort
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceReadPort
from armi_interaction.api import (
    InteractionOtherHumanPartySnapshot,
    InteractionOtherHumanReadPort,
    InteractionOtherHumanTimelineSource,
)
from armi_kernel.application import (
    ArtifactId,
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
from armi_kernel.contracts import Instant, OpaqueCursor
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)


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


class PostgreSQLOtherHumanRecordQuery:
    __slots__ = (
        "_catalog",
        "_codec",
        "_effect",
        "_evidence",
        "_factory",
        "_interaction",
        "_storage",
        "_visibility",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        environment_id: UUID,
        cursor_key: bytes,
        data_root: Path,
        max_object_bytes: int,
        visibility: DataRightsVisibilityPort,
        interaction: InteractionOtherHumanReadPort,
        evidence: EvidenceReadPort,
        effect: EffectOperationReadPort,
        catalog: ArtifactCatalogPort,
    ) -> None:
        self._codec = OtherHumanRecordCursorCodec(
            key=cursor_key, environment_id=environment_id
        )
        self._factory = factory
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        )
        self._visibility = visibility
        self._interaction = interaction
        self._evidence = evidence
        self._effect = effect
        self._catalog = catalog

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_parties(
        self, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanPartyRecordPage:
        boundary: UUID | None = None
        if cursor is not None:
            boundary = self._uuid(
                self._codec.decode(cursor, "parties", "all", {"before_id"})["before_id"]
            )
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                rows = await self._interaction.list_other_human_parties(
                    unit_of_work.transaction, before_id=boundary, limit=limit + 1
                )
        except RuntimeTransactionFailure:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None
        more = len(rows) > limit
        visible_ids = await self._visible_party_ids(tuple(row.party_id for row in rows))
        visible = tuple(row for row in rows if row.party_id in visible_ids)[:limit]
        items = tuple(self._party(row) for row in visible)
        next_cursor = (
            self._codec.encode(
                "parties", "all", {"before_id": str(visible[-1].party_id)}
            )
            if more and visible
            else None
        )
        return OtherHumanPartyRecordPage(items, next_cursor)

    async def list_scenes(
        self, party_id: UUID, *, limit: int, cursor: OpaqueCursor | None = None
    ) -> OtherHumanSceneRecordPage:
        boundary: UUID | None = None
        scope = str(party_id)
        if cursor is not None:
            boundary = self._uuid(
                self._codec.decode(cursor, "scenes", scope, {"before_id"})["before_id"]
            )
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                party_row = await self._interaction.other_human_party(
                    unit_of_work.transaction, party_id=party_id
                )
                rows = await self._interaction.list_other_human_scenes(
                    unit_of_work.transaction,
                    party_id=party_id,
                    before_id=boundary,
                    limit=limit + 1,
                )
        except RuntimeTransactionFailure:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None
        if party_row is None or not await self._party_visible(party_id):
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-NOT-VISIBLE")
        more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(
            OtherHumanSceneRecord(
                row.scene_id,
                row.scene_key,
                row.status,
                row.timeline_count,
                row.latest_at,
            )
            for row in visible
        )
        next_cursor = (
            self._codec.encode(
                "scenes", scope, {"before_id": str(visible[-1].scene_id)}
            )
            if more and visible
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
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                exists = await self._interaction.other_human_scene_exists(
                    connection, party_id=party_id, scene_id=scene_id
                )
                rows = await self._interaction.other_human_timeline(
                    connection,
                    party_id=party_id,
                    scene_id=scene_id,
                    before_at=None if boundary is None else boundary[0].value,
                    before_id=None if boundary is None else boundary[1],
                    limit=limit + 1,
                )
                resolved: list[
                    tuple[InteractionOtherHumanTimelineSource, ArtifactRef]
                ] = []
                for row in rows[:limit]:
                    resolved.append((row, await self._artifact_ref(unit_of_work, row)))
        except RuntimeTransactionFailure:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None
        if not exists or not await self._party_visible(party_id):
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-NOT-VISIBLE")
        more = len(rows) > limit
        visible = rows[:limit]
        items = tuple([await self._timeline_item(row, ref) for row, ref in resolved])
        next_cursor = (
            self._codec.encode(
                "timeline",
                scope,
                {
                    "before_at": Instant(visible[-1].occurred_at).to_wire(),
                    "before_id": str(visible[-1].timeline_item_id),
                },
            )
            if more and visible
            else None
        )
        return OtherHumanTimelineRecordPage(party_id, scene_id, items, next_cursor)

    async def _artifact_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        row: InteractionOtherHumanTimelineSource,
    ) -> ArtifactRef:
        if row.source_kind == "other_human_input":
            evidence_id = await self._evidence.find_by_interaction(
                unit_of_work.transaction, interaction_id=row.source_ref
            )
            if evidence_id is None:
                raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE")
            artifact_id = (
                await self._evidence.snapshot(
                    unit_of_work.transaction, evidence_id=evidence_id
                )
            ).artifact_id
        else:
            effect = await self._effect.by_effect_id(
                unit_of_work.transaction, effect_id=row.source_ref
            )
            if effect is None:
                raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE")
            artifact_id = effect.payload_artifact_id
        return await self._catalog.get(unit_of_work, ArtifactId(artifact_id))

    async def _timeline_item(
        self, row: InteractionOtherHumanTimelineSource, ref: ArtifactRef
    ) -> OtherHumanTimelineRecord:
        try:
            if ref.media_type != "text/plain":
                raise ValueError
            text = ""
            async with await self._storage.open_verified(ref) as stream:
                text = (await stream.read()).decode("utf-8", errors="strict")
            return OtherHumanTimelineRecord(
                row.timeline_item_id,
                row.source_ref,
                OtherHumanRecordDirection(
                    "received" if row.source_kind == "other_human_input" else "sent"
                ),
                row.result_status,
                text,
                row.occurred_at,
            )
        except ArtifactViolation, ValueError, UnicodeError, OSError:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None

    async def _party_visible(self, party_id: UUID) -> bool:
        return party_id in await self._visible_party_ids((party_id,))

    async def _visible_party_ids(self, party_ids: tuple[UUID, ...]) -> frozenset[UUID]:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                visible: set[UUID] = set()
                for party_id in party_ids:
                    restrictions = await self._visibility.party_restrictions(
                        unit_of_work.transaction, party_id
                    )
                    if "delete_related" not in restrictions:
                        visible.add(party_id)
                return frozenset(visible)
        except RuntimeTransactionFailure:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None

    @staticmethod
    def _party(row: InteractionOtherHumanPartySnapshot) -> OtherHumanPartyRecord:
        return OtherHumanPartyRecord(
            row.party_id,
            row.identity_key,
            row.display_label,
            row.scene_count,
            row.timeline_count,
            row.latest_at,
        )

    @staticmethod
    def _uuid(value: str) -> UUID:
        try:
            parsed = UUID(value)
        except ValueError:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR") from None
        if parsed.version != 7:
            raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-CURSOR")
        return parsed


__all__ = ("OtherHumanRecordCursorCodec", "PostgreSQLOtherHumanRecordQuery")
