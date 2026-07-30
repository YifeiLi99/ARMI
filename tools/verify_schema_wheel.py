"""Verify that a Runtime wheel contains the generated schema mirror."""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

_RESOURCE_PREFIX = "armi_runtime/composition/runtime_resources/schema/"
_FILES = (
    "checks/invariants.sql",
    "manifests/database-role-manifest.json",
    "manifests/schema-manifest.json",
    "migrations/0001_m0_baseline.sql",
    "migrations/0002_database_permissions.sql",
    "migrations/0003_content_addressed_artifacts.sql",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        with zipfile.ZipFile(args.wheel) as archive:
            names = set(archive.namelist())
            for relative in _FILES:
                packaged = f"{_RESOURCE_PREFIX}{relative}"
                if packaged not in names:
                    raise ValueError("DB-SCHEMA-MISSING")
                expected = (
                    root / "apps/armi-runtime/src/armi_runtime/composition/"
                    "runtime_resources/schema" / relative
                ).read_bytes()
                if archive.read(packaged) != expected:
                    raise ValueError("DB-MANIFEST-DRIFT")
            forbidden = [
                name
                for name in names
                if name.startswith("schema/")
                or (name.endswith(".sql") and not name.startswith(_RESOURCE_PREFIX))
            ]
            if forbidden:
                raise ValueError("DB-SCHEMA-DIRTY")
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        code = str(error) if str(error).startswith("DB-") else "DB-MANIFEST-DRIFT"
        print(f"{code}: Runtime wheel schema resources are invalid", file=sys.stderr)
        return 1
    print("schema-wheel: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
