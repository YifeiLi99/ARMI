"""Generate the frozen modular baseline and ordered migration manifests."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = (
    ROOT / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
BASELINE_ROOT = SCHEMA_ROOT / "baseline"
MIGRATIONS_ROOT = SCHEMA_ROOT / "migrations"
BASELINE_ID = "baseline"
BASELINE_DOCUMENTS = (
    "00_namespace.sql",
    "10_runtime_and_subject.sql",
    "20_artifacts_parties_interactions.sql",
    "30_cognition_and_provenance.sql",
    "40_life_memory_relationships.sql",
    "50_activities_and_maintenance.sql",
    "60_actions_work_and_effects.sql",
    "70_web_codex_audit_data_rights.sql",
    "80_cross_domain_constraints_and_indexes.sql",
    "90_static_catalog.sql",
    "99_privileges.sql",
)
TABLE_PATTERN = re.compile(rb"\bCREATE TABLE armi\.([a-z][a-z0-9_]*)\s*\(")
DROP_PATTERN = re.compile(rb"\bDROP TABLE armi\.([a-z][a-z0-9_]*)\b")
MIGRATION_ID = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def table_changes(value: bytes) -> tuple[list[str], list[str]]:
    created = sorted(
        {match.group(1).decode("ascii") for match in TABLE_PATTERN.finditer(value)}
    )
    dropped = sorted(
        {match.group(1).decode("ascii") for match in DROP_PATTERN.finditer(value)}
    )
    return created, dropped


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def combined_digest(documents: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        documents,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return digest(encoded)


def current_catalog_digest() -> str:
    path = BASELINE_ROOT / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        catalog_digest = value["catalog_sha256"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return "sha256:" + "0" * 64
    return (
        catalog_digest
        if type(catalog_digest) is str and DIGEST.fullmatch(catalog_digest)
        else "sha256:" + "0" * 64
    )


def main() -> int:
    baseline_files = sorted(path.name for path in BASELINE_ROOT.glob("*.sql"))
    if baseline_files != sorted(BASELINE_DOCUMENTS):
        raise RuntimeError("schema baseline documents have drifted")
    documents: list[dict[str, str]] = []
    tables: set[str] = set()
    for name in BASELINE_DOCUMENTS:
        raw = (BASELINE_ROOT / name).read_bytes()
        if not raw.strip():
            raise RuntimeError(f"baseline document is empty: {name}")
        created, dropped = table_changes(raw)
        if dropped or tables.intersection(created):
            raise RuntimeError(f"baseline table declarations are invalid: {name}")
        tables.update(created)
        documents.append({"path": name, "sha256": digest(raw)})
    write_json(
        BASELINE_ROOT / "manifest.json",
        {
            "baseline_id": BASELINE_ID,
            "catalog_sha256": current_catalog_digest(),
            "documents": documents,
            "schema_version": "armi.schema-baseline.v1",
            "sha256": combined_digest(documents),
            "tables": sorted(tables),
        },
    )

    MIGRATIONS_ROOT.mkdir(exist_ok=True)
    migration_manifest_path = MIGRATIONS_ROOT / "manifest.json"
    existing_targets: dict[str, str] = {}
    if migration_manifest_path.exists():
        existing_manifest = json.loads(
            migration_manifest_path.read_text(encoding="utf-8")
        )
        existing_targets = {
            str(item["path"]): str(item.get("target_catalog_sha256", ""))
            for item in existing_manifest.get("migrations", [])
            if isinstance(item, dict) and "path" in item
        }
    migrations: list[dict[str, object]] = []
    previous_id: str | None = None
    target_tables = set(tables)
    for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
        migration_id = path.stem
        if MIGRATION_ID.fullmatch(migration_id) is None or (
            previous_id is not None and migration_id <= previous_id
        ):
            raise RuntimeError(f"invalid migration order: {path.name}")
        raw = path.read_bytes()
        created, dropped = table_changes(raw)
        if set(created).intersection(target_tables):
            raise RuntimeError(f"migration recreates an existing table: {path.name}")
        if not set(dropped).issubset(target_tables):
            raise RuntimeError(f"migration drops an unknown table: {path.name}")
        target_tables.difference_update(dropped)
        target_tables.update(created)
        migrations.append(
            {
                "creates_tables": created,
                "drops_tables": dropped,
                "migration_id": migration_id,
                "path": path.name,
                "sha256": digest(raw),
                "target_catalog_sha256": existing_targets.get(
                    path.name, "sha256:" + "0" * 64
                ),
            }
        )
        previous_id = migration_id
    write_json(
        migration_manifest_path,
        {
            "baseline_id": BASELINE_ID,
            "migrations": migrations,
            "schema_version": "armi.schema-migrations.v1",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
