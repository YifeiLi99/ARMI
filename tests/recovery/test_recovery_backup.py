from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from armi_runtime.composition.recovery import verify_recovery_backup
from armi_runtime.composition.runtime_errors import RuntimeViolation


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    artifact = bundle / "artifacts/objects/sha256/ab/cd/abcdef"
    artifact.parent.mkdir(parents=True)
    dump = bundle / "database.dump"
    dump.write_bytes(b"custom-database-dump")
    artifact.write_bytes(b"artifact-content")
    manifest = {
        "schema_version": "armi.recovery-backup.v1",
        "backup_id": "019c0000-0000-7000-8000-000000000001",
        "environment_id": "019c0000-0000-7000-8000-000000000002",
        "created_at": "2026-08-08T00:00:00Z",
        "source_connection_identity": "sha256:" + "1" * 64,
        "database": {
            "dump_path": "database.dump",
            "dump_bytes": dump.stat().st_size,
            "dump_digest": _digest(dump.read_bytes()),
            "catalog_digest": "sha256:" + "2" * 64,
            "history": [["baseline", "baseline", "sha256:" + "3" * 64]],
            "tables": [{"name": "subjects", "rows": 1}],
            "subjects": [],
        },
        "artifacts": [
            {
                "artifact_id": "019c0000-0000-7000-8000-000000000003",
                "content_digest": _digest(artifact.read_bytes()),
                "byte_size": artifact.stat().st_size,
                "storage_locator": "objects/sha256/ab/cd/abcdef",
            }
        ],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle


def test_offline_recovery_bundle_verifies_all_content(tmp_path: Path) -> None:
    result = verify_recovery_backup(_bundle(tmp_path))

    assert result.status == "verified"
    assert result.table_count == 1
    assert result.row_count == 1
    assert result.artifact_count == 1


def test_offline_recovery_bundle_rejects_artifact_corruption(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    artifact = bundle / "artifacts/objects/sha256/ab/cd/abcdef"
    artifact.write_bytes(b"corrupt")

    with pytest.raises(RuntimeViolation, match="recovery bundle is corrupt"):
        verify_recovery_backup(bundle)


def test_offline_recovery_bundle_rejects_dump_corruption(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "database.dump").write_bytes(b"corrupt")

    with pytest.raises(RuntimeViolation, match="recovery bundle is corrupt"):
        verify_recovery_backup(bundle)


def test_offline_recovery_bundle_rejects_missing_artifact(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "artifacts/objects/sha256/ab/cd/abcdef").unlink()

    with pytest.raises(RuntimeViolation, match="recovery bundle is corrupt"):
        verify_recovery_backup(bundle)
