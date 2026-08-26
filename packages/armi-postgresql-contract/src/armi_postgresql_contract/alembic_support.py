"""Execution helpers for the immutable SQL baseline."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from alembic import op

from .catalog_fingerprint import database_catalog_digest
from .schema_resources import role_policy_digest, schema_resource_digest


def execute_schema_sql(group: str, name: str) -> None:
    context = op.get_context()
    assert context is not None and context.config is not None
    schema_root = cast(Path, context.config.attributes["schema_root"])
    definition = (
        schema_root.joinpath(group, name).read_bytes().decode("utf-8", "strict")
    )
    bind = op.get_bind()
    assert bind is not None and bind.connection.driver_connection is not None
    with bind.connection.driver_connection.cursor() as cursor:
        cursor.execute(definition, prepare=False)


def finalize_schema_identity() -> None:
    context = op.get_context()
    assert context is not None and context.config is not None
    schema_root = cast(Path, context.config.attributes["schema_root"])
    bind = op.get_bind()
    assert bind is not None and bind.connection.driver_connection is not None
    connection = bind.connection.driver_connection
    connection.execute(
        """
        UPDATE armi.schema_baseline_identity
        SET resource_digest = %s,
            installed_catalog_digest = %s,
            role_policy_digest = %s
        WHERE singleton_key
        """,
        (
            schema_resource_digest(schema_root),
            database_catalog_digest(connection),
            role_policy_digest(schema_root),
        ),
    )


__all__ = ("execute_schema_sql", "finalize_schema_identity")
