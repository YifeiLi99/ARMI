"""Replace column-level writes with explicit table-level DML capabilities."""

from __future__ import annotations

from collections import defaultdict

from alembic import op
from armi_runtime.adapters.persistence.database_capabilities import (
    DML_CAPABILITIES_0002,
)

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_REVOKE_COLUMN_DML = """
DO $armi$
DECLARE
    grant_row record;
BEGIN
    FOR grant_row IN
        SELECT grantee.rolname AS role_name,
               namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               privilege.privilege_type,
               string_agg(
                   pg_catalog.quote_ident(attribute.attname),
                   ', ' ORDER BY attribute.attnum
               ) AS column_names
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS privilege
        JOIN pg_catalog.pg_roles AS grantee
          ON grantee.oid = privilege.grantee
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'v')
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND grantee.rolname IN ('armi_runtime', 'armi_admin')
          AND privilege.privilege_type IN ('INSERT', 'UPDATE')
        GROUP BY grantee.rolname, namespace.nspname, relation.relname,
                 privilege.privilege_type
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE %s (%s) ON TABLE %I.%I FROM %I',
            grant_row.privilege_type,
            grant_row.column_names,
            grant_row.schema_name,
            grant_row.relation_name,
            grant_row.role_name
        );
    END LOOP;
END
$armi$
"""

_REVOKE_TABLE_DML = """
DO $armi$
DECLARE
    grant_row record;
BEGIN
    FOR grant_row IN
        SELECT grantee.rolname AS role_name,
               namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               privilege.privilege_type
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) AS privilege
        JOIN pg_catalog.pg_roles AS grantee
          ON grantee.oid = privilege.grantee
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'v')
          AND grantee.rolname IN ('armi_runtime', 'armi_admin')
          AND privilege.privilege_type IN ('INSERT', 'UPDATE', 'DELETE')
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE %s ON TABLE %I.%I FROM %I',
            grant_row.privilege_type,
            grant_row.schema_name,
            grant_row.relation_name,
            grant_row.role_name
        );
    END LOOP;
END
$armi$
"""


def upgrade() -> None:
    op.execute(_REVOKE_COLUMN_DML)
    op.execute(_REVOKE_TABLE_DML)
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for role, table, operation in sorted(DML_CAPABILITIES_0002):
        grouped[(role, operation)].append(table)
    for (role, operation), tables in sorted(grouped.items()):
        qualified = ", ".join(f"armi.{table}" for table in tables)
        op.execute(f"GRANT {operation} ON TABLE {qualified} TO {role}")


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
