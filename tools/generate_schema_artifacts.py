"""Generate or verify the authoritative S009 schema manifest and wheel mirror."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import rfc8785

_SCHEMA_ROOT = Path("schema")
_MIRROR_ROOT = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
_MIGRATION = Path("migrations/0001_m0_baseline.sql")
_INVARIANTS = Path("checks/invariants.sql")
_MANIFEST = Path("manifests/schema-manifest.json")
_MIGRATION_NAME = re.compile(
    r"^(?P<version>[0-9]{4})_(?P<name>[a-z][a-z0-9_]{0,63})\.sql$"
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_text_file(path: Path) -> bytes:
    try:
        value = path.read_bytes()
    except OSError:
        raise ValueError("DB-SCHEMA-MISSING") from None
    if value.startswith(b"\xef\xbb\xbf") or b"\r" in value or not value.endswith(b"\n"):
        raise ValueError("DB-MANIFEST-DRIFT")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("DB-MANIFEST-DRIFT") from None
    return value


def build_manifest(schema_root: Path) -> dict[str, object]:
    migration_path = schema_root / _MIGRATION
    invariant_path = schema_root / _INVARIANTS
    match = _MIGRATION_NAME.fullmatch(migration_path.name)
    if match is None or int(match.group("version")) != 1:
        raise ValueError("DB-SCHEMA-GAP")
    migration = _require_text_file(migration_path)
    invariants = _require_text_file(invariant_path)
    migration_digest = _digest(migration)
    migration_set_input = (
        f"1\tschema/{_MIGRATION.as_posix()}\t{migration_digest}\n".encode()
    )
    return {
        "schema_version": "armi.schema-manifest.v1",
        "postgresql": {
            "product": "PostgreSQL",
            "version": "18.4",
            "server_version_num": 180004,
        },
        "database": {
            "encoding": "UTF8",
            "timezone": "UTC",
            "locale_provider": "builtin",
            "locale": "C.UTF-8",
        },
        "target": {"schema": "armi", "version": 1},
        "migrations": [
            {
                "version": 1,
                "name": match.group("name"),
                "path": f"schema/{_MIGRATION.as_posix()}",
                "sha256": migration_digest,
            }
        ],
        "migration_set_sha256": _digest(migration_set_input),
        "invariants": {
            "path": f"schema/{_INVARIANTS.as_posix()}",
            "sha256": _digest(invariants),
            "read_only": True,
        },
        "allowed_objects": [
            {
                "kind": "table",
                "name": "armi.schema_migrations",
                "logical_owner": "schema-governance",
                "activation_step": "M0-S009",
            }
        ],
        "deferred_objects": [
            {"scope": "artifacts", "activation_step": "M0-S012"},
            {"scope": "audit_events", "activation_step": "M0-S013"},
            {"scope": "durable_work", "activation_step": "M0-S014"},
            {"scope": "outbox_items", "activation_step": "M0-S015"},
            {"scope": "authority_state", "activation_step": "M0-S016"},
            {"scope": "recovery_state", "activation_step": "M0-S017"},
        ],
        "runtime_upgrade_allowed": False,
        "formal_roles_and_grants_activation_step": "M0-S010",
    }


def canonical_manifest_bytes(value: dict[str, object]) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def generated_files(root: Path) -> dict[Path, bytes]:
    schema_root = root / _SCHEMA_ROOT
    manifest = canonical_manifest_bytes(build_manifest(schema_root))
    return {
        _MANIFEST: manifest,
        _MIGRATION: _require_text_file(schema_root / _MIGRATION),
        _INVARIANTS: _require_text_file(schema_root / _INVARIANTS),
    }


def _matches(root: Path, generated: dict[Path, bytes]) -> bool:
    schema_root = root / _SCHEMA_ROOT
    mirror_root = root / _MIRROR_ROOT
    return all(
        (schema_root / relative).is_file()
        and (schema_root / relative).read_bytes() == value
        and (mirror_root / relative).is_file()
        and (mirror_root / relative).read_bytes() == value
        for relative, value in generated.items()
    )


def _write(root: Path, generated: dict[Path, bytes]) -> None:
    for base in (root / _SCHEMA_ROOT, root / _MIRROR_ROOT):
        for relative, value in generated.items():
            destination = base / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        generated = generated_files(root)
        if args.write:
            _write(root, generated)
        else:
            temporary_root = root / ".tmp"
            temporary_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="schema-", dir=temporary_root
            ) as path:
                scratch = Path(path)
                for relative, value in generated.items():
                    target = scratch / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(value)
                if {
                    relative: (scratch / relative).read_bytes()
                    for relative in generated
                } != generated or not _matches(root, generated):
                    print(
                        "DB-MANIFEST-DRIFT: schema artifacts drifted", file=sys.stderr
                    )
                    return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        code = str(error) if str(error).startswith("DB-") else "DB-MANIFEST-DRIFT"
        print(f"{code}: schema artifacts are invalid", file=sys.stderr)
        return 1
    print("schema-artifacts: written" if args.write else "schema-artifacts: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
