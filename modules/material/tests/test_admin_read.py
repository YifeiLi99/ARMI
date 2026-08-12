from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from armi_artifact_store import build_life_material_artifact
from armi_material._admin import PostgreSQLMaterialAdminRead
from armi_material.api import MaterialViolation


class _Reader(PostgreSQLMaterialAdminRead):
    def __init__(self, artifact_root: Path, rows: list[tuple[Any, ...]]) -> None:
        super().__init__(
            "postgresql://unused",
            expected_role="armi_test_admin",
            artifact_root=artifact_root,
            max_object_bytes=1_000_000,
        )
        self._test_rows = rows

    def _rows(self, subject_id: UUID) -> list[tuple[Any, ...]]:
        del subject_id
        return self._test_rows


def _artifact(artifact_root: Path, body: str) -> tuple[UUID, str, str, int]:
    artifact_bytes = build_life_material_artifact(body.encode("utf-8"))
    content_digest = f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    digest_hex = content_digest[7:]
    locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
    path = artifact_root / Path(locator)
    path.parent.mkdir(parents=True)
    path.write_bytes(artifact_bytes)
    return uuid7(), content_digest, locator, len(artifact_bytes)


def _row(
    artifact: tuple[UUID, str, str, int],
    *,
    privacy_status: str = "private",
    deleted_at: datetime | None = None,
) -> tuple[Any, ...]:
    artifact_id, content_digest, _locator, size = artifact
    occurred_at = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    return (
        uuid7(),
        uuid7(),
        "diary",
        2,
        occurred_at,
        occurred_at,
        deleted_at,
        2,
        "隐藏随记",
        {"mood": "quiet"},
        "active",
        privacy_status,
        artifact_id,
        content_digest,
        "application/json",
        size,
        "life.material.content",
        "private",
        "verified",
    )


def test_private_snapshot_reads_hidden_and_deleted_materials(tmp_path: Path) -> None:
    artifact_root = tmp_path.resolve() / "artifacts"
    private_body = "ARMI 标记为 private 的正文"
    deleted_body = "已经 tombstone 的旧正文"
    reader = _Reader(
        artifact_root,
        [
            _row(_artifact(artifact_root, private_body)),
            _row(
                _artifact(artifact_root, deleted_body),
                privacy_status="restricted",
                deleted_at=datetime(2026, 8, 5, 11, 0, tzinfo=UTC),
            ),
        ],
    )

    snapshot = reader.private_snapshot(uuid7())

    assert snapshot.truncated is False
    assert {item.body for item in snapshot.items} == {private_body, deleted_body}
    assert any(item.deleted_at is not None for item in snapshot.items)


def test_private_snapshot_fails_closed_on_corrupt_artifact(tmp_path: Path) -> None:
    artifact_root = tmp_path.resolve() / "artifacts"
    artifact = _artifact(artifact_root, "不能返回被篡改的正文")
    (artifact_root / Path(artifact[2])).write_bytes(b"corrupt")
    reader = _Reader(artifact_root, [_row(artifact)])

    with pytest.raises(MaterialViolation, match="MATERIAL-OBSERVATION-ARTIFACT"):
        reader.private_snapshot(uuid7())
