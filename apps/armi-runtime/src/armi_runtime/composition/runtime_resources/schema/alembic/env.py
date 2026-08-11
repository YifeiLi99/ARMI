"""Alembic environment driven only through ARMI's credential boundary."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("DB-SCHEMA-CONNECTION")

context.configure(
    connection=connection,
    target_metadata=None,
    transactional_ddl=True,
    transaction_per_migration=True,
    version_table="alembic_version",
    version_table_schema="armi",
)

with context.begin_transaction():
    context.run_migrations()
