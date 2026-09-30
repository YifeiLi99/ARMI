"""Verified source identities for forward-only schema migration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from .catalog_fingerprint import database_catalog_payload
from .database_contract import (
    PostgreSQLContractError,
    PostgreSQLContractEvidence,
    verify_contract_identity,
)
from .schema_resources import (
    REVISION_RESOURCES,
    role_policy_digest,
    schema_resource_digest,
)

# This mutable-0000 source was inspected before restoring migrations. It differs
# only in the columns/checks bridged by 0001; never accept arbitrary old digests.
LEGACY_BASELINE_DIGEST = (
    "sha256:17633393372ba2edbad67e1c1497c654737ccabfa30a854eff31849785a42ba7"
)

# Recorded from the inspected source DDL. ACL/role facts are verified separately;
# column positions differ between an ALTER upgrade and a fresh installation.
_SOURCE_SHAPES = {
    LEGACY_BASELINE_DIGEST: "f96c7b907f9a8f61d8f0472f5f653ca051233feb0bb6606da4dd38014ac56e52",
    "sha256:c2180c1b600b07dd2560f62c70949c65b6bf697ff7778e8cc9d423174198d9cd": "32bb55a9b0508332e815dbeb15ddcc883c8451733181bf5d472c3e9a9cf70963",
    "sha256:bded28836bf0d6e972f5566f9c5b58adac76277b953553184b2c8ac86d86ab7e": "32bb55a9b0508332e815dbeb15ddcc883c8451733181bf5d472c3e9a9cf70963",
}


def _source_shape(connection: Any) -> str:
    kinds = {
        "schema",
        "relations",
        "columns",
        "constraints",
        "indexes",
        "extensions",
        "routines",
        "triggers",
        "types",
    }
    payload = [
        item
        for item in cast(
            list[dict[str, Any]], json.loads(database_catalog_payload(connection))
        )
        if item["kind"] in kinds
    ]
    columns = next(item for item in payload if item["kind"] == "columns")
    columns["rows"] = [row[:1] + row[2:] for row in columns["rows"]]
    cast(list[list[Any]], columns["rows"]).sort(key=lambda row: (row[0], row[1]))
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_migration_source(
    connection: Any, *, resource_root: Path
) -> PostgreSQLContractEvidence:
    revisions = connection.execute(
        "SELECT version_num FROM armi.alembic_version"
    ).fetchall()
    identities = connection.execute(
        "SELECT resource_digest FROM armi.schema_baseline_identity WHERE singleton_key"
    ).fetchall()
    if len(revisions) != 1 or len(identities) != 1:
        raise PostgreSQLContractError("DB-SCHEMA-MIGRATION-SOURCE")
    revision, digest = str(revisions[0][0]), str(identities[0][0])
    if revision not in REVISION_RESOURCES:
        raise PostgreSQLContractError("DB-SCHEMA-MIGRATION-SOURCE")
    expected = schema_resource_digest(resource_root, revision=revision)
    if digest != expected and not (
        revision == "0000" and digest == LEGACY_BASELINE_DIGEST
    ):
        raise PostgreSQLContractError("DB-SCHEMA-MIGRATION-SOURCE")
    # Prove the installed catalog and ACL still match the recorded source. A
    # recognized resource digest alone is insufficient to bless manual drift.
    evidence = verify_contract_identity(
        connection,
        expected_resource=digest,
        expected_role_policy=role_policy_digest(resource_root),
        expected_revision=revision,
    )
    if revision in {"0000", "0001"} and _source_shape(connection) != _SOURCE_SHAPES.get(
        digest
    ):
        raise PostgreSQLContractError("DB-SCHEMA-MIGRATION-SOURCE")
    return evidence


__all__ = ("LEGACY_BASELINE_DIGEST", "verify_migration_source")
