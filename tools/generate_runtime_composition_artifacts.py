"""Generate or verify packaged S008 Runtime composition resources."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from armi_runtime.composition.manifest import (
    build_composition_manifest,
    canonical_manifest_bytes,
)

_TARGET = Path("apps/armi-runtime/src/armi_runtime/composition/runtime_resources")
_CONFIG = {
    "runtime.defaults.toml": Path("config/runtime.defaults.toml"),
    "runtime.schema.json": Path("config/runtime.schema.json"),
    "runtime-config-manifest.json": Path("config/runtime-config-manifest.json"),
}
_CREATOR = Path("apps/armi-runtime/src/armi_runtime/interfaces/creator_web_resources")
_SCHEMA = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
_SCHEMA_FILES = (
    "checks/invariants.sql",
    "manifests/database-role-manifest.json",
    "manifests/schema-manifest.json",
    "migrations/0001_m0_baseline.sql",
    "migrations/0002_database_permissions.sql",
    "migrations/0003_content_addressed_artifacts.sql",
    "migrations/0004_normal_audit_foundation.sql",
    "migrations/0005_durable_work_and_outbox.sql",
    "migrations/0006_unique_birth.sql",
    "migrations/0007_runtime_authority.sql",
    "migrations/0008_runtime_recovery.sql",
    "migrations/0009_scene_timeline_query.sql",
)


def _generate(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    config_resources: dict[str, bytes] = {}
    for target_name, source_relative in _CONFIG.items():
        value = (root / source_relative).read_bytes()
        config_resources[target_name] = value
        (output / target_name).write_bytes(value)
    creator_manifest = (root / _CREATOR / "manifest.json").read_bytes()
    creator_openapi = (root / _CREATOR / "openapi.json").read_bytes()
    birth_contract = (root / _TARGET / "birth-contract.manifest.json").read_bytes()
    (output / "birth-contract.manifest.json").write_bytes(birth_contract)
    schema_resources = {
        name: (root / _SCHEMA / name).read_bytes() for name in _SCHEMA_FILES
    }
    manifest = build_composition_manifest(
        config_resources=config_resources,
        creator_manifest=creator_manifest,
        creator_openapi=creator_openapi,
        birth_contract=birth_contract,
        schema_resources=schema_resources,
    )
    (output / "runtime-composition.manifest.json").write_bytes(
        canonical_manifest_bytes(manifest)
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        name: (root / name).read_bytes()
        for name in (
            *_CONFIG,
            "birth-contract.manifest.json",
            "runtime-composition.manifest.json",
        )
        if (root / name).is_file()
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="runtime-composition-",
            dir=temporary_root,
        ) as temporary:
            generated = Path(temporary)
            _generate(root, generated)
            target = root / _TARGET
            if args.write:
                target.mkdir(parents=True, exist_ok=True)
                for name, value in _files(generated).items():
                    destination = target / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(value)
            elif _files(generated) != _files(target):
                print(
                    "CMP-MANIFEST-DRIFT: packaged composition resources drifted",
                    file=sys.stderr,
                )
                return 1
        print(
            "runtime-composition: written"
            if args.write
            else "runtime-composition: verified"
        )
        return 0
    except OSError:
        print(
            "CMP-RESOURCE-MISSING: a composition input is unavailable",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
