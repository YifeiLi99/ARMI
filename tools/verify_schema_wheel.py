"""Verify that a Runtime wheel contains the generated schema mirror."""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

try:
    from tools.candidate_bundle import sha256_bytes, verify_schema_archive
except ModuleNotFoundError:  # Direct execution from the tools directory.
    from candidate_bundle import sha256_bytes, verify_schema_archive


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
            digest, target_version, _ = verify_schema_archive(archive)
            manifest_path = (
                root / "apps/armi-runtime/src/armi_runtime/composition/"
                "runtime_resources/schema/manifests/schema-manifest.json"
            )
            if digest != sha256_bytes(manifest_path.read_bytes()):
                raise ValueError("DB-MANIFEST-DRIFT")
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        code = getattr(error, "code", None) or (
            str(error) if str(error).startswith("DB-") else "DB-MANIFEST-DRIFT"
        )
        print(f"{code}: Runtime wheel schema resources are invalid", file=sys.stderr)
        return 1
    print(f"schema-wheel: verified target v{target_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
