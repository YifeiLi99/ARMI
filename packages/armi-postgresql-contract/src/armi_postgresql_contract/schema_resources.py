"""Immutable resources and identities for the sole PostgreSQL baseline."""

from __future__ import annotations

import ast
import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Final

BASELINE_IDENTITY: Final = "armi.schema-baseline.v11"
EXPECTED_REVISION: Final = "0000"
BASELINE_DOCUMENTS: Final = (
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
_RESOURCE_FILES: Final = (
    "alembic/env.py",
    "alembic/script.py.mako",
    "alembic/versions/0000_baseline.py",
    *(f"baseline/{name}" for name in BASELINE_DOCUMENTS),
)


def schema_resource_root() -> Path:
    root = files("armi_postgresql_contract").joinpath("resources", "schema")
    try:
        path = Path(str(root))
    except TypeError:
        raise RuntimeError("DB-SCHEMA-RESOURCE") from None
    if not path.is_dir():
        raise RuntimeError("DB-SCHEMA-RESOURCE")
    return path


def _digest_entries(entries: tuple[tuple[str, bytes], ...]) -> str:
    digest = hashlib.sha256()
    for name, content in entries:
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def schema_resource_digest(root: Path | None = None) -> str:
    resource_root = root or schema_resource_root()
    entries: list[tuple[str, bytes]] = []
    for relative in _RESOURCE_FILES:
        path = resource_root.joinpath(*relative.split("/"))
        if not path.is_file():
            raise RuntimeError("DB-SCHEMA-RESOURCE")
        entries.append((relative, path.read_bytes()))
    return _digest_entries(tuple(entries))


def role_policy_digest(root: Path | None = None) -> str:
    resource_root = root or schema_resource_root()
    content = resource_root.joinpath("baseline", "99_privileges.sql").read_bytes()
    return _digest_entries((("baseline/99_privileges.sql", content),))


def verify_revision_source(root: Path | None = None) -> None:
    resource_root = root or schema_resource_root()
    path = resource_root / "alembic" / "versions" / "0000_baseline.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except OSError, UnicodeError, SyntaxError:
        raise RuntimeError("DB-SCHEMA-RESOURCE") from None
    assignments: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "revision",
                "down_revision",
                "branch_labels",
                "depends_on",
                "_DOCUMENTS",
            }:
                assignments[target.id] = ast.literal_eval(node.value)
    if assignments != {
        "revision": EXPECTED_REVISION,
        "down_revision": None,
        "branch_labels": None,
        "depends_on": None,
        "_DOCUMENTS": BASELINE_DOCUMENTS,
    }:
        raise RuntimeError("DB-SCHEMA-RESOURCE")


__all__ = (
    "BASELINE_DOCUMENTS",
    "BASELINE_IDENTITY",
    "EXPECTED_REVISION",
    "role_policy_digest",
    "schema_resource_digest",
    "schema_resource_root",
    "verify_revision_source",
)
