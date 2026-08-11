"""Shared execution helper for immutable pre-Alembic SQL revisions."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from alembic import op


def execute_schema_sql(group: str, name: str) -> None:
    context = op.get_context()
    assert context is not None
    config = context.config
    assert config is not None
    schema_root = cast(Path, config.attributes["schema_root"])
    definition = (
        schema_root.joinpath(group, name).read_bytes().decode("utf-8", "strict")
    )
    bind = op.get_bind()
    assert bind is not None
    driver_connection = bind.connection.driver_connection
    assert driver_connection is not None
    with driver_connection.cursor() as cursor:
        cursor.execute(definition, prepare=False)


__all__ = ("execute_schema_sql",)
