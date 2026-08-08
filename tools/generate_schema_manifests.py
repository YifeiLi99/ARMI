"""Generate the frozen baseline and ordered migration manifests."""

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
BASELINE_PATH = BASELINE_ROOT / "baseline.sql"
TABLE_PATTERN = re.compile(rb"\bCREATE TABLE armi\.([a-z][a-z0-9_]*)\s*\(")
DROP_PATTERN = re.compile(rb"\bDROP TABLE armi\.([a-z][a-z0-9_]*)\b")
MIGRATION_ID = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")


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


def main() -> int:
    baseline_files = sorted(BASELINE_ROOT.glob("*.sql"))
    if baseline_files != [BASELINE_PATH]:
        raise RuntimeError("schema baseline must be the single baseline.sql document")
    raw = BASELINE_PATH.read_bytes()
    created, dropped = table_changes(raw)
    if dropped:
        raise RuntimeError("baseline SQL cannot drop tables")
    tables = set(created)
    write_json(
        BASELINE_ROOT / "manifest.json",
        {
            "baseline_id": BASELINE_ID,
            "path": BASELINE_PATH.name,
            "schema_version": "armi.schema-baseline.v1",
            "sha256": digest(raw),
            "tables": sorted(tables),
        },
    )

    MIGRATIONS_ROOT.mkdir(exist_ok=True)
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
            }
        )
        previous_id = migration_id
    write_json(
        MIGRATIONS_ROOT / "manifest.json",
        {
            "baseline_id": BASELINE_ID,
            "migrations": migrations,
            "schema_version": "armi.schema-migrations.v1",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
