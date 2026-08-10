from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from uuid import UUID, uuid7

import pytest
from armi_artifact_store.life_material_codec import (
    build_life_material_artifact,
)
from armi_kernel.application import CreatorLifeMaterialQueryViolation
from armi_runtime.adapters.persistence.life_records import PostgreSQLLifeRecordQuery


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _Transaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class _Connection:
    def __init__(
        self,
        *,
        creator_party_id: UUID,
        subject_id: UUID,
        material_row: tuple[Any, ...] | None,
    ) -> None:
        self.creator_party_id = creator_party_id
        self.subject_id = subject_id
        self.material_row = material_row
        self.material_sql = ""

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if "FROM armi.parties" in statement:
            assert parameters == (self.creator_party_id,)
            return _Cursor((1,))
        if "FROM armi.subjects" in statement:
            return _Cursor((self.subject_id,))
        if "FROM armi.life_materials AS material" in statement:
            self.material_sql = statement
            assert self.material_row is not None
            assert parameters == (self.material_row[0], self.subject_id)
            return _Cursor(self.material_row)
        return _Cursor(None)


class _ConnectionContext:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection_value = connection

    def connection(self, *, timeout: float) -> _ConnectionContext:
        assert timeout == 1.0
        return _ConnectionContext(self.connection_value)


def _write_artifact(data_root: Path, artifact_bytes: bytes) -> tuple[str, str]:
    content_digest = f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    digest_hex = content_digest[7:]
    locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
    path = data_root / "artifacts" / Path(locator)
    path.parent.mkdir(parents=True)
    (data_root / "artifacts" / "staging").mkdir()
    (data_root / "artifacts" / "quarantine").mkdir()
    path.write_bytes(artifact_bytes)
    return content_digest, locator


def test_creator_material_query_reads_only_current_visible_verified_body(
    tmp_path: Path,
) -> None:
    data_root = tmp_path.resolve() / "data"
    body = "经过完整性校验的正文"
    artifact_bytes = build_life_material_artifact(body.encode("utf-8"))
    content_digest, _locator = _write_artifact(data_root, artifact_bytes)
    material_id, revision_id, artifact_id = uuid7(), uuid7(), uuid7()
    creator_party_id, subject_id = uuid7(), uuid7()
    occurred_at = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    row: tuple[Any, ...] = (
        material_id,
        revision_id,
        "diary",
        2,
        occurred_at,
        occurred_at,
        2,
        "雨天随记",
        {"mood": "quiet"},
        "active",
        "creator_visible",
        artifact_id,
        content_digest,
        len(artifact_bytes),
        "application/json",
        "life.material.content",
        "private",
        "verified",
        1,
    )
    connection = _Connection(
        creator_party_id=creator_party_id,
        subject_id=subject_id,
        material_row=row,
    )
    query = PostgreSQLLifeRecordQuery(
        "postgresql://unused",
        environment_id=uuid7(),
        creator_party_id=creator_party_id,
        cursor_key=b"k" * 32,
        data_root=data_root,
        max_object_bytes=1_000_000,
        pool_timeout_seconds=1,
    )
    query._pool = _Pool(connection)  # pyright: ignore[reportPrivateUsage,reportAttributeAccessIssue]

    item = asyncio.run(query.get_creator_visible(material_id))

    assert item is not None
    assert item.body == body
    assert item.metadata == (("mood", "quiet"),)
    assert "material.deleted_at IS NULL" in connection.material_sql
    assert "revision.privacy_status = 'creator_visible'" in connection.material_sql

    path = next((data_root / "artifacts" / "objects").rglob(content_digest[7:]))
    path.write_bytes(b"corrupt")
    with pytest.raises(
        CreatorLifeMaterialQueryViolation,
        match="creator life material query failed",
    ):
        asyncio.run(query.get_creator_visible(material_id))
