from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest
from armi_admin.persistence.observation_gateway import AdminObservationGateway
from armi_kernel.contracts import Digest
from armi_runtime.adapters.artifacts.life_material_codec import (
    build_life_material_artifact,
)


class _Observation(AdminObservationGateway):
    def __init__(
        self,
        *,
        artifact_root: Path,
        subject: tuple[Any, ...],
        materials: list[tuple[Any, ...]],
    ) -> None:
        super().__init__(
            "postgresql://unused",
            expected_role="armi_test_admin",
            artifact_root=artifact_root,
        )
        self.subject = subject
        self.materials = materials

    def _one(
        self,
        statement: object,
        parameters: tuple[Any, ...] = (),
    ) -> tuple[Any, ...] | None:
        del parameters
        assert "FROM armi.subjects" in str(statement)
        return self.subject

    def _all(
        self,
        statement: object,
        parameters: tuple[Any, ...] = (),
    ) -> list[tuple[Any, ...]]:
        text = str(statement)
        if "subject_component_heads" in text:
            return []
        if "life_materials AS material" in text:
            assert parameters == (self.subject[0],)
            assert "LIMIT 101" in text
            return self.materials
        raise AssertionError("unexpected Admin observation query")


def _artifact(artifact_root: Path, body: str) -> tuple[UUID, str, str, int]:
    artifact_bytes = build_life_material_artifact(body.encode("utf-8"))
    content_digest = f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
    digest_hex = content_digest[7:]
    locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
    path = artifact_root / Path(locator)
    path.parent.mkdir(parents=True)
    path.write_bytes(artifact_bytes)
    return uuid7(), content_digest, locator, len(artifact_bytes)


def _material_row(
    artifact: tuple[UUID, str, str, int],
    *,
    body: str,
    privacy_status: str,
    deleted_at: datetime | None,
) -> tuple[Any, ...]:
    artifact_id, content_digest, locator, size = artifact
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
        Digest.from_bytes(body.encode("utf-8")).value,
        artifact_id,
        content_digest,
        "application/json",
        size,
        locator,
        "life.material.content",
        "private",
        "verified",
        1,
    )


def test_private_subject_snapshot_observes_hidden_and_deleted_materials_only_explicitly(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path.resolve() / "artifacts"
    private_body = "ARMI 标记为 private 的正文"
    deleted_body = "已经 tombstone 的旧正文"
    rows = [
        _material_row(
            _artifact(artifact_root, private_body),
            body=private_body,
            privacy_status="private",
            deleted_at=None,
        ),
        _material_row(
            _artifact(artifact_root, deleted_body),
            body=deleted_body,
            privacy_status="restricted",
            deleted_at=datetime(2026, 8, 5, 11, 0, tzinfo=UTC),
        ),
    ]
    subject_id = uuid7()
    observation = _Observation(
        artifact_root=artifact_root,
        subject=(subject_id, 3, 1, "alive", uuid7(), uuid7()),
        materials=rows,
    )

    summary = observation.subject_snapshot(private=False)
    hidden = observation.subject_snapshot(private=True)

    assert "materials" not in summary
    assert private_body not in str(summary)
    assert hidden["materials_truncated"] is False
    materials = hidden["materials"]
    assert isinstance(materials, list)
    assert {item["body"] for item in materials} == {private_body, deleted_body}
    assert {item["privacy_status"] for item in materials} == {
        "private",
        "restricted",
    }
    assert any(item["deleted_at"] is not None for item in materials)


def test_private_subject_snapshot_fails_closed_on_corrupt_material_artifact(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path.resolve() / "artifacts"
    body = "不能返回被篡改的正文"
    artifact = _artifact(artifact_root, body)
    row = _material_row(
        artifact,
        body=body,
        privacy_status="private",
        deleted_at=None,
    )
    locator = artifact[2]
    (artifact_root / Path(locator)).write_bytes(b"corrupt")
    observation = _Observation(
        artifact_root=artifact_root,
        subject=(uuid7(), 3, 1, "alive", uuid7(), uuid7()),
        materials=[row],
    )

    with pytest.raises(ValueError, match="ADMIN-OBSERVATION-MATERIAL-ARTIFACT"):
        observation.subject_snapshot(private=True)
