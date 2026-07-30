"""Generate or verify authoritative schema and database-role governance artifacts."""

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
_INVARIANTS = Path("checks/invariants.sql")
_MANIFEST = Path("manifests/schema-manifest.json")
_ROLE_MANIFEST = Path("manifests/database-role-manifest.json")
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


def build_role_manifest() -> dict[str, object]:
    safe_attributes = {
        "superuser": False,
        "createdb": False,
        "createrole": False,
        "replication": False,
        "bypassrls": False,
    }
    return {
        "schema_version": "armi.database-roles.v1",
        "postgresql_version": "18.4",
        "environment_id": {
            "format": "lowercase canonical UUIDv7",
            "physical_role_template": "armi_{environment_uuid_hex}_{role_class}",
            "role_classes": ["runtime", "admin", "migrator"],
        },
        "capability_roles": [
            {
                "name": name,
                "login": False,
                "inherit": False,
                **safe_attributes,
            }
            for name in (
                "armi_owner",
                "armi_migrator",
                "armi_runtime",
                "armi_admin",
            )
        ],
        "login_roles": [
            {
                "class": role_class,
                "login": True,
                "inherit": True,
                **safe_attributes,
            }
            for role_class in ("runtime", "admin", "migrator")
        ],
        "memberships": [
            {
                "member_class": "runtime",
                "role": "armi_runtime",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "admin",
                "role": "armi_admin",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "migrator",
                "role": "armi_migrator",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "migrator",
                "role": "armi_owner",
                "inherit": False,
                "set": True,
                "admin": False,
            },
        ],
        "database_privileges": {
            "public": [],
            "owner": ["CREATE"],
            "runtime": ["CONNECT"],
            "admin": ["CONNECT"],
            "migrator": ["CONNECT"],
            "temporary_allowed": False,
            "create_allowed": False,
        },
        "session": {
            "search_path": ["pg_catalog", "armi"],
            "checkout_requires_session_user": True,
            "checkout_requires_current_user_reset": True,
        },
        "objects": [
            {
                "kind": "schema",
                "name": "armi",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["USAGE"],
                    "armi_admin": ["USAGE"],
                    "armi_migrator": ["USAGE"],
                },
            },
            {
                "kind": "table",
                "name": "armi.schema_migrations",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": ["SELECT"],
                    "armi_migrator": ["SELECT"],
                },
            },
            {
                "kind": "table",
                "name": "armi.artifacts",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": [],
                    "armi_migrator": [],
                },
                "column_grants": {
                    "armi_runtime": {
                        "INSERT": [
                            "artifact_id",
                            "content_digest",
                            "media_type",
                            "byte_size",
                            "storage_locator",
                            "logical_kind",
                            "producer_kind",
                            "producer_trace_id",
                            "privacy_scope",
                            "schema_version",
                        ],
                        "UPDATE": ["integrity_status"],
                    },
                    "armi_admin": {},
                    "armi_migrator": {},
                },
            },
        ],
        "default_privileges": [],
        "security_definer": {
            "entries": [],
            "not_applicable_reason": (
                "M0-S012 has no business or administration function requiring "
                "privilege elevation."
            ),
            "required_search_path": ["pg_catalog", "armi", "pg_temp"],
            "public_execute": False,
        },
        "credential_acl": {
            "policy": "tools/windows-credential-acl-policy.json",
            "activation_step": "M0-S035",
            "active": False,
        },
    }


def build_manifest(schema_root: Path, role_manifest_bytes: bytes) -> dict[str, object]:
    migration_paths = sorted((schema_root / "migrations").glob("*.sql"))
    if not migration_paths:
        raise ValueError("DB-SCHEMA-MISSING")
    migrations: list[dict[str, object]] = []
    migration_set_input = bytearray()
    for expected_version, migration_path in enumerate(migration_paths, start=1):
        relative = migration_path.relative_to(schema_root)
        match = _MIGRATION_NAME.fullmatch(migration_path.name)
        if match is None or int(match.group("version")) != expected_version:
            raise ValueError("DB-SCHEMA-GAP")
        migration = _require_text_file(migration_path)
        migration_digest = _digest(migration)
        path = f"schema/{relative.as_posix()}"
        migrations.append(
            {
                "version": expected_version,
                "name": match.group("name"),
                "path": path,
                "sha256": migration_digest,
            }
        )
        migration_set_input.extend(
            f"{expected_version}\t{path}\t{migration_digest}\n".encode()
        )
    invariant_path = schema_root / _INVARIANTS
    invariants = _require_text_file(invariant_path)
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
        "target": {"schema": "armi", "version": len(migrations)},
        "migrations": migrations,
        "migration_set_sha256": _digest(bytes(migration_set_input)),
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
            },
            {
                "kind": "table",
                "name": "armi.artifacts",
                "logical_owner": "artifact-catalog",
                "activation_step": "M0-S012",
            },
        ],
        "deferred_objects": [
            {"scope": "audit_events", "activation_step": "M0-S013"},
            {"scope": "durable_work", "activation_step": "M0-S014"},
            {"scope": "outbox_items", "activation_step": "M0-S015"},
            {"scope": "authority_state", "activation_step": "M0-S016"},
            {"scope": "recovery_state", "activation_step": "M0-S017"},
        ],
        "runtime_upgrade_allowed": False,
        "database_role_manifest": {
            "path": f"schema/{_ROLE_MANIFEST.as_posix()}",
            "sha256": _digest(role_manifest_bytes),
            "activation_step": "M0-S010",
        },
    }


def canonical_manifest_bytes(value: dict[str, object]) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def generated_files(root: Path) -> dict[Path, bytes]:
    schema_root = root / _SCHEMA_ROOT
    role_manifest = canonical_manifest_bytes(build_role_manifest())
    manifest = canonical_manifest_bytes(build_manifest(schema_root, role_manifest))
    generated = {
        _MANIFEST: manifest,
        _ROLE_MANIFEST: role_manifest,
        _INVARIANTS: _require_text_file(schema_root / _INVARIANTS),
    }
    for migration_path in sorted((schema_root / "migrations").glob("*.sql")):
        relative = migration_path.relative_to(schema_root)
        generated[relative] = _require_text_file(migration_path)
    return generated


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
