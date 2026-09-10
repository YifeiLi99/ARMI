"""Configuration replacement evidence contains identity and versions, never values."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid7

from pydantic import BaseModel, ConfigDict, Field

from armi_local_control.layout import environment_control_root

from .paths import has_reparse_point


class ConfigurationWriteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    environment_id: str
    write_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: str
    expected_version: str
    version: str
    file_device: int
    file_identity: int


def write_identity(binding_identity: str, key: str) -> str:
    return hashlib.sha256(
        (binding_identity + "\0configuration\0" + key).encode()
    ).hexdigest()


def evidence_path(root: Path, environment_id: str, write_id: str) -> Path:
    if len(write_id) != 64 or any(char not in "0123456789abcdef" for char in write_id):
        raise ValueError("ADMIN-CONFIG-WRITE-IDENTITY")
    path = (
        environment_control_root(root, environment_id)
        / "configuration-writes"
        / (write_id + ".json")
    )
    if has_reparse_point(path, root=Path(path.anchor)):
        raise ValueError("ADMIN-CONFIG-PATH")
    return path


def prepare_write(
    root: Path,
    environment_id: str,
    write_id: str,
    target: Path,
    temporary: Path,
    expected_version: str,
    version: str,
) -> None:
    identity = temporary.stat()
    evidence = ConfigurationWriteEvidence(
        environment_id=environment_id,
        write_id=write_id,
        target=target.relative_to(root).as_posix(),
        expected_version=expected_version,
        version=version,
        file_device=identity.st_dev,
        file_identity=identity.st_ino,
    )
    path = evidence_path(root, environment_id, write_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name("." + str(uuid7()) + ".tmp")
    try:
        with pending.open("xb") as stream:
            stream.write((evidence.model_dump_json(indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def verify_write(
    root: Path,
    environment_id: str,
    write_id: str,
    *,
    target: Path,
    expected_version: str,
) -> str | None:
    path = evidence_path(root, environment_id, write_id)
    if not path.exists():
        return None
    if path.stat().st_size > 8192:
        raise ValueError("ADMIN-CONFIG-WRITE-EVIDENCE")
    evidence = ConfigurationWriteEvidence.model_validate_json(path.read_bytes())
    if (
        evidence.environment_id != environment_id
        or evidence.write_id != write_id
        or evidence.target != target.relative_to(root).as_posix()
        or evidence.expected_version != expected_version
    ):
        raise ValueError("ADMIN-CONFIG-WRITE-EVIDENCE")
    if has_reparse_point(target, root=root):
        raise ValueError("ADMIN-CONFIG-PATH")
    try:
        with target.open("rb") as stream:
            identity = os.fstat(stream.fileno())
            if (
                identity.st_size > 1024 * 1024
                or not evidence.file_identity
                or identity.st_ino != evidence.file_identity
                or identity.st_dev != evidence.file_device
            ):
                return None
            digest = "sha256:" + hashlib.sha256(stream.read()).hexdigest()
    except FileNotFoundError:
        return None
    return evidence.version if digest == evidence.version else None


__all__ = (
    "ConfigurationWriteEvidence",
    "prepare_write",
    "verify_write",
    "write_identity",
)
