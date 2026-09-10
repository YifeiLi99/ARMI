"""Seal a standalone wheel installation without build-machine path dependencies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from armi_admin.application.package_identity import admin_package_set_digest
from armi_postgresql_contract import (
    BASELINE_IDENTITY,
    role_policy_digest,
    schema_resource_digest,
)


def seal(root: Path) -> None:
    root = root.resolve(strict=True)
    site = root / "runtime/python/Lib/site-packages"
    if not (site / "armi_admin").is_dir():
        raise ValueError("INSTALLER-NOT-A-PAYLOAD")
    if {path.name for path in root.glob("*.exe")} != {"ARMI.exe"}:
        raise ValueError("INSTALLER-ENTRYPOINT-INVENTORY")
    # Wheel console launchers contain absolute shebangs. Public native launchers
    # live at the program root; Runtime workers use the private sys.executable.
    scripts = (root / "runtime/python/Scripts").resolve()
    if not scripts.is_relative_to(root):
        raise ValueError("INSTALLER-SEAL-BOUNDARY")
    if scripts.exists():
        shutil.rmtree(scripts)
    for metadata in site.glob("*.dist-info"):
        removed = {"direct_url.json", "uv_cache.json"}
        for name in removed:
            (metadata / name).unlink(missing_ok=True)
        record = metadata / "RECORD"
        if not record.exists():
            continue
        with record.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        kept = [row for row in rows if (site / row[0]).is_file()]
        with record.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(kept)
    for cache in sorted(
        root.rglob("__pycache__"), key=lambda path: len(path.parts), reverse=True
    ):
        if not cache.resolve().is_relative_to(root):
            raise ValueError("INSTALLER-SEAL-BOUNDARY")
        shutil.rmtree(cache)
    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "bundle.json":
            with path.open("rb") as stream:
                inventory[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    manifest: dict[str, object] = {
        "schema_version": "armi.windows-bundle.v1",
        "product_version": "0.0.0",
        "target": "windows-11-x64",
        "signed": False,
        "database": {
            "postgresql": "18.4",
            "vector": "0.8.6",
            "pg_trgm": "1.6",
            "baseline": BASELINE_IDENTITY,
            "schema_digest": schema_resource_digest(),
            "role_policy_digest": role_policy_digest(),
        },
        "package_set_digest": admin_package_set_digest(),
        "files": inventory,
    }
    manifest["package_id"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    (root / "bundle.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    seal(parser.parse_args().root)
