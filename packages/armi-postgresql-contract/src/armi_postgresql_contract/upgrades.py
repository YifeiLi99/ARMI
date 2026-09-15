"""Explicit, signed-resource forward upgrades; ordinary startup never calls this."""

from __future__ import annotations

import json
from typing import Any

from .catalog_fingerprint import database_catalog_digest, database_structure_digest
from .database_contract import (
    PostgreSQLContractError,
    verify_contract_identity,
    verify_postgresql_contract,
)
from .schema_resources import (
    BASELINE_IDENTITY,
    role_policy_digest,
    schema_resource_digest,
    schema_resource_root,
)


def upgrade_plan() -> dict[str, Any]:
    root = schema_resource_root().parent / "upgrades"
    plan = json.loads((root / "v17-to-v18.json").read_text(encoding="utf-8"))
    if (
        plan["format"] != "armi.database-upgrade.v1"
        or plan["target_baseline"] != BASELINE_IDENTITY
    ):
        raise PostgreSQLContractError("DB-UPGRADE-RESOURCE")
    return plan


def upgrade_target() -> dict[str, str]:
    return {
        "postgresql": "18.4",
        "vector": "0.8.6",
        "pg_trgm": "1.6",
        "baseline": BASELINE_IDENTITY,
        "schema_digest": schema_resource_digest(),
        "role_policy_digest": role_policy_digest(),
    }


def supported_upgrade(source: dict[str, Any], target: dict[str, Any]) -> bool:
    plan = upgrade_plan()
    return source == plan["source"] and target == upgrade_target()


def check_upgrade(connection: Any) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT baseline_identity FROM armi.schema_baseline_identity"
    ).fetchall()
    if rows == [(BASELINE_IDENTITY,)]:
        verify_postgresql_contract(connection)
        return {"state": "current", "target": upgrade_target()}
    source = upgrade_plan()["source"]
    verify_contract_identity(
        connection,
        expected_baseline=source["baseline"],
        expected_resource=source["schema_digest"],
        expected_role_policy=source["role_policy_digest"],
    )
    return {"state": "upgrade_required", "source": source, "target": upgrade_target()}


def verify_upgrade_resources() -> str:
    path = schema_resource_root().parent / "upgrades" / "target-structure.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if (
        evidence["schema_digest"] != schema_resource_digest()
        or evidence["baseline"] != BASELINE_IDENTITY
    ):
        raise PostgreSQLContractError("DB-UPGRADE-REFERENCE-STALE")
    digest = evidence["structure_digest"]
    if (
        not isinstance(digest, str)
        or len(digest) != 71
        or not digest.startswith("sha256:")
    ):
        raise PostgreSQLContractError("DB-UPGRADE-RESOURCE")
    return digest


def apply_upgrade(connection: Any) -> dict[str, Any]:
    """Apply within a caller-owned transaction; never commit or start processes."""
    expected_structure = verify_upgrade_resources()
    connection.execute("SET LOCAL lock_timeout = '5s'")
    connection.execute("SET LOCAL statement_timeout = '120s'")
    connection.execute(
        "LOCK TABLE armi.schema_baseline_identity IN ACCESS EXCLUSIVE MODE"
    )
    status = check_upgrade(connection)
    if status["state"] == "current":
        return status
    root = schema_resource_root()
    for step in upgrade_plan()["steps"]:
        path = (root / step).resolve()
        if not path.is_relative_to(root.parent.resolve()) or path.suffix != ".sql":
            raise PostgreSQLContractError("DB-UPGRADE-RESOURCE")
        connection.execute(path.read_text(encoding="utf-8"), prepare=False)
    if database_structure_digest(connection) != expected_structure:
        raise PostgreSQLContractError("DB-UPGRADE-TARGET-DRIFT")
    connection.execute(
        "UPDATE armi.schema_baseline_identity SET resource_digest=%s, "
        "installed_catalog_digest=%s,role_policy_digest=%s",
        (
            schema_resource_digest(),
            database_catalog_digest(connection),
            role_policy_digest(),
        ),
    )
    verify_postgresql_contract(connection)
    return {"state": "upgraded", "target": upgrade_target()}


__all__ = (
    "apply_upgrade",
    "check_upgrade",
    "supported_upgrade",
    "upgrade_plan",
    "upgrade_target",
    "verify_upgrade_resources",
)
