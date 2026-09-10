"""Read and verify installed program identity independently of persistent data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from armi_local_control.configuration.paths import has_reparse_point
from pydantic import BaseModel, ConfigDict, Field


class BundleDatabase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    postgresql: str
    vector: str
    pg_trgm: str
    baseline: str
    schema_digest: str
    role_policy_digest: str


class ProgramBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.windows-bundle.v1"]
    product_version: str
    target: Literal["windows-11-x64"]
    signed: bool
    database: BundleDatabase
    package_set_digest: str
    package_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    files: dict[str, str]

    @classmethod
    def read(cls, root: Path) -> ProgramBundle:
        if has_reparse_point(root, root=Path(root.anchor)):
            raise ValueError("INSTALLER-PROGRAM-PATH")
        result = cls.model_validate_json((root / "bundle.json").read_bytes())
        content = result.model_dump(mode="json", exclude={"package_id"})
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        if digest != result.package_id:
            raise ValueError("INSTALLER-PACKAGE-IDENTITY")
        return result

    def verify(self, root: Path) -> None:
        root = root.resolve(strict=True)
        for relative, expected in self.files.items():
            path = root / relative
            if not path.resolve().is_relative_to(root) or has_reparse_point(
                path, root=root
            ):
                raise ValueError("INSTALLER-PACKAGE-BOUNDARY")
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError("INSTALLER-PACKAGE-CORRUPT")
