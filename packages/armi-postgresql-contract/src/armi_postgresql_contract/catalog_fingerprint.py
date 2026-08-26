"""Canonical PostgreSQL catalog evidence shared by Runtime and Admin."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, cast

_CATALOG_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "schema",
        """
        SELECT namespace.nspname, owner.rolname
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = namespace.nspowner
        WHERE namespace.nspname = 'armi'
        ORDER BY namespace.nspname
        """,
    ),
    (
        "relations",
        """
        SELECT relation.relname, relation.relkind, owner.rolname,
               relation.relpersistence
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
        ORDER BY relation.relkind, relation.relname
        """,
    ),
    (
        "columns",
        """
        SELECT relation.relname, attribute.attnum, attribute.attname,
               pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid),
               attribute.attidentity, attribute.attgenerated
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attnum > 0
         AND NOT attribute.attisdropped
        LEFT JOIN pg_catalog.pg_attrdef AS default_value
          ON default_value.adrelid = relation.oid
         AND default_value.adnum = attribute.attnum
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
        ORDER BY relation.relname, attribute.attnum
        """,
    ),
    (
        "constraints",
        """
        SELECT relation.relname, constraint_value.conname,
               constraint_value.contype,
               constraint_value.condeferrable,
               constraint_value.condeferred,
               pg_catalog.pg_get_constraintdef(constraint_value.oid, true)
        FROM pg_catalog.pg_constraint AS constraint_value
        JOIN pg_catalog.pg_class AS relation
          ON relation.oid = constraint_value.conrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'armi'
        ORDER BY relation.relname, constraint_value.conname
        """,
    ),
    (
        "indexes",
        """
        SELECT table_value.relname, index_value.relname,
               index_state.indisunique, index_state.indisprimary,
               index_state.indisvalid,
               pg_catalog.pg_get_indexdef(index_value.oid)
        FROM pg_catalog.pg_index AS index_state
        JOIN pg_catalog.pg_class AS index_value
          ON index_value.oid = index_state.indexrelid
        JOIN pg_catalog.pg_class AS table_value
          ON table_value.oid = index_state.indrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = table_value.relnamespace
        WHERE namespace.nspname = 'armi'
        ORDER BY table_value.relname, index_value.relname
        """,
    ),
    (
        "schema_acl",
        """
        SELECT namespace.nspname,
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                namespace.nspacl,
                pg_catalog.acldefault('n', namespace.nspowner)
            )
        ) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'armi'
        ORDER BY 1, 2, 3, 4
        """,
    ),
    (
        "relation_acl",
        """
        SELECT relation.relname, relation.relkind,
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                         ELSE 'r'::"char" END,
                    relation.relowner
                )
            )
        ) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
        ORDER BY 1, 2, 3, 4, 5
        """,
    ),
    (
        "column_acl",
        """
        SELECT relation.relname, attribute.attname,
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attnum > 0
         AND NOT attribute.attisdropped
        CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'armi'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND attribute.attacl IS NOT NULL
        ORDER BY 1, 2, 3, 4, 5
        """,
    ),
    (
        "extensions",
        """
        SELECT extension.extname, extension.extversion, namespace.nspname
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE extension.extname IN ('vector', 'pg_trgm')
        ORDER BY extension.extname
        """,
    ),
    (
        "routines",
        """
        SELECT routine.proname,
               pg_catalog.pg_get_function_identity_arguments(routine.oid),
               pg_catalog.pg_get_function_result(routine.oid),
               routine.prokind, routine.provolatile, routine.prosecdef,
               owner.rolname, pg_catalog.pg_get_functiondef(routine.oid)
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = routine.proowner
        WHERE namespace.nspname = 'armi'
        ORDER BY 1, 2
        """,
    ),
    (
        "routine_acl",
        """
        SELECT routine.proname,
               pg_catalog.pg_get_function_identity_arguments(routine.oid),
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(routine.proacl, pg_catalog.acldefault('f', routine.proowner))
        ) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'armi'
        ORDER BY 1, 2, 3, 4, 5
        """,
    ),
    (
        "triggers",
        """
        SELECT relation.relname, trigger_value.tgname,
               trigger_value.tgenabled,
               pg_catalog.pg_get_triggerdef(trigger_value.oid, true)
        FROM pg_catalog.pg_trigger AS trigger_value
        JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_value.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'armi' AND NOT trigger_value.tgisinternal
        ORDER BY 1, 2
        """,
    ),
    (
        "types",
        """
        SELECT type_value.typname, type_value.typtype,
               pg_catalog.format_type(type_value.oid, NULL), owner.rolname
        FROM pg_catalog.pg_type AS type_value
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = type_value.typnamespace
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = type_value.typowner
        WHERE namespace.nspname = 'armi'
          AND type_value.typtype IN ('e', 'd', 'c', 'r')
        ORDER BY 1, 2
        """,
    ),
    (
        "default_acl",
        """
        SELECT owner.rolname, COALESCE(namespace.nspname, ''),
               default_acl.defaclobjtype,
               COALESCE(grantee.rolname, 'PUBLIC'),
               acl.privilege_type, acl.is_grantable
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_roles AS owner ON owner.oid = default_acl.defaclrole
        LEFT JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = default_acl.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl
        LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE owner.rolname LIKE 'armi%' OR namespace.nspname = 'armi'
        ORDER BY 1, 2, 3, 4, 5, 6
        """,
    ),
    (
        "roles",
        """
        SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb,
               rolcanlogin, rolreplication, rolbypassrls, rolconnlimit
        FROM pg_catalog.pg_roles
        WHERE rolname LIKE 'armi%'
        ORDER BY rolname
        """,
    ),
    (
        "role_memberships",
        """
        SELECT granted.rolname, member.rolname, membership.admin_option,
               membership.inherit_option, membership.set_option
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
        WHERE granted.rolname LIKE 'armi%' OR member.rolname LIKE 'armi%'
        ORDER BY 1, 2
        """,
    ),
)


def _safe(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    return str(value)


def _rows(value: Sequence[Sequence[object]]) -> list[list[object]]:
    return [[_safe(item) for item in row] for row in value]


def database_catalog_payload(
    connection: Any, *, normalize_column_ordinals: bool = True
) -> bytes:
    """Return stable UTF-8 evidence without PostgreSQL-local object identifiers."""

    original = connection.execute("SHOW search_path").fetchone()
    if original is None:
        raise RuntimeError("search_path is unavailable")
    connection.execute(
        "SELECT pg_catalog.set_config('search_path', 'pg_catalog', false)"
    )
    try:
        evidence: list[dict[str, object]] = [
            {"kind": kind, "rows": _rows(connection.execute(query).fetchall())}
            for kind, query in _CATALOG_QUERIES
        ]
        if normalize_column_ordinals:
            columns = next(item for item in evidence if item["kind"] == "columns")
            ordinals: dict[str, int] = {}
            for row in cast(list[list[object]], columns["rows"]):
                table_name = str(row[0])
                ordinal = ordinals.get(table_name, 0) + 1
                ordinals[table_name] = ordinal
                row[1] = ordinal
    finally:
        connection.execute(
            "SELECT pg_catalog.set_config('search_path', %s, false)",
            (str(original[0]),),
        )
    return json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def database_catalog_digest(connection: Any) -> str:
    return f"sha256:{hashlib.sha256(database_catalog_payload(connection)).hexdigest()}"


__all__ = (
    "database_catalog_digest",
    "database_catalog_payload",
)
