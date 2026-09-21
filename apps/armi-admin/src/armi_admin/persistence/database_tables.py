"""Structured physical table access through the packaged maintenance policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, LiteralString, cast

from armi_postgresql_contract.table_policy import TABLE_OWNERSHIP
from armi_runtime_foundation import PostgreSQLAdminParameter, PostgreSQLAdminTransaction
from psycopg import sql
from pydantic import JsonValue

from armi_admin.application.database_contracts import (
    DatabaseChange,
    DatabaseFilter,
    DatabaseQueryRequest,
)


class DatabaseTableError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatabaseColumn:
    name: str
    type_name: str
    nullable: bool
    generated: bool
    default: str | None


@dataclass(frozen=True, slots=True)
class DatabaseTable:
    name: str
    kind: str
    columns: tuple[DatabaseColumn, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[dict[str, Any], ...]

    @property
    def writable(self) -> bool:
        policy = TABLE_OWNERSHIP.get(self.name)
        return self.kind == "r" and policy is not None and policy.maintenance_writable

    def column(self, name: str) -> DatabaseColumn:
        for column in self.columns:
            if column.name == name:
                return column
        raise DatabaseTableError("ADMIN-DATABASE-FIELD")

    def describe(self) -> dict[str, Any]:
        policy = TABLE_OWNERSHIP.get(self.name)
        online = {
            "subjective_memories": (
                "memory",
                "head_version",
                ("create", "update", "delete"),
            ),
            "relationships": (
                "relationship",
                "head_version",
                ("create", "update", "delete"),
            ),
            "life_materials": (
                "material",
                "head_version",
                ("create", "update", "delete"),
            ),
            "activities": ("activity", "head_version", ("create", "update", "delete")),
            "prompt_revisions": (
                "prompt",
                "revision_no; 0 before first creation",
                ("create", "update", "delete"),
            ),
            "mind_revisions": ("mind", "mind_version", ("update",)),
            "subject_component_revisions": (
                "subject_state",
                "component_version",
                ("update",),
            ),
            "mood_revisions": ("mood", "mood_version", ("update",)),
        }.get(self.name)
        return {
            "table": self.name,
            "kind": "table" if self.kind == "r" else "view",
            "owner": policy.owner if policy else "runtime",
            "columns": [
                {
                    "name": column.name,
                    "type": column.type_name,
                    "nullable": column.nullable,
                    "generated": column.generated,
                    "default": column.default,
                }
                for column in self.columns
            ],
            "primary_key": list(self.primary_key),
            "foreign_keys": list(self.foreign_keys),
            "permissions": {
                "query": True,
                "insert": self.writable,
                "update": self.writable and bool(self.primary_key),
                "delete": self.writable and bool(self.primary_key),
            },
            "write_mode": "maintenance" if self.writable else "read_only",
            "online_management": None
            if online is None
            else {
                "operation": "content_write",
                "owner": online[0],
                "actions": list(online[2]),
                "expected_version_field": online[1],
                "subject_field": "subjects.subject_id",
                "restriction": "Versioned owner writes retain history and reject busy targets. Singleton components use subject_id as object_id; personality_anchor is immutable.",
            },
            "restriction": "Runtime and business processes must stop; PostgreSQL stays running."
            if self.writable
            else "Use the owning module's formal identity, permission or result operation.",
            "value_encoding": "PostgreSQL text or null; JSON columns accept JSON values. Exact numeric, array, bytea and timestamp values are returned as text.",
        }


def _statement(value: sql.Composable) -> str:
    return value.as_string()


def _table(name: str) -> sql.Identifier:
    return sql.Identifier("armi", name)


def table_catalog(tx: PostgreSQLAdminTransaction) -> dict[str, DatabaseTable]:
    relations = tx.execute(
        "SELECT c.oid, c.relname, c.relkind FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='armi' AND c.relkind IN ('r','v','m') ORDER BY c.relname"
    ).fetchall()
    result: dict[str, DatabaseTable] = {}
    for oid, name, kind in relations:
        name = str(name)
        if (
            str(kind) == "r"
            and name not in TABLE_OWNERSHIP
            and name != "alembic_version"
        ):
            raise DatabaseTableError("ADMIN-DATABASE-POLICY-MISSING")
        fields = tx.execute(
            "SELECT a.attname, pg_catalog.format_type(a.atttypid,a.atttypmod), "
            "NOT a.attnotnull, a.attgenerated <> '' OR a.attidentity <> '', "
            "pg_catalog.pg_get_expr(d.adbin,d.adrelid) "
            "FROM pg_catalog.pg_attribute a LEFT JOIN pg_catalog.pg_attrdef d "
            "ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
            "WHERE a.attrelid=%s::oid AND a.attnum>0 AND NOT a.attisdropped "
            "ORDER BY a.attnum",
            (int(str(oid)),),
        ).fetchall()
        keys = tx.execute(
            "SELECT a.attname FROM pg_catalog.pg_index i "
            "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position) "
            "JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum "
            "WHERE i.indrelid=%s::oid AND i.indisprimary ORDER BY k.position",
            (int(str(oid)),),
        ).fetchall()
        references = tx.execute(
            "SELECT c.conname, pg_catalog.pg_get_constraintdef(c.oid) "
            "FROM pg_catalog.pg_constraint c WHERE c.conrelid=%s::oid "
            "AND c.contype='f' ORDER BY c.conname",
            (int(str(oid)),),
        ).fetchall()
        result[name] = DatabaseTable(
            name,
            str(kind),
            tuple(
                DatabaseColumn(
                    str(n),
                    str(t),
                    bool(nullable),
                    bool(generated),
                    None if default is None else str(default),
                )
                for n, t, nullable, generated, default in fields
            ),
            tuple(str(row[0]) for row in keys),
            tuple({"name": str(n), "definition": str(d)} for n, d in references),
        )
    return result


def _parameter(column: DatabaseColumn, value: JsonValue) -> PostgreSQLAdminParameter:
    if value is None:
        return None
    if column.type_name in {"json", "jsonb"}:
        if isinstance(value, dict) and set(value) == {"postgresql_json"}:
            exact = value["postgresql_json"]
            if not isinstance(exact, str):
                raise DatabaseTableError("ADMIN-DATABASE-VALUE-TYPE")
            return exact
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value, allow_nan=False)
    raise DatabaseTableError("ADMIN-DATABASE-VALUE-TYPE")


def _cast(column: DatabaseColumn) -> sql.Composed:
    # Type names come only from the verified database catalog, never a request.
    return sql.SQL("CAST(%s AS {})").format(
        sql.SQL(cast(LiteralString, column.type_name))
    )


def _selection(table: DatabaseTable) -> sql.Composed:
    fields: list[sql.Composable] = [
        sql.SQL("{}::text").format(sql.Identifier(column.name))
        for column in table.columns
    ]
    if table.kind == "r":
        fields.append(sql.SQL("xmin::text"))
    return sql.SQL(", ").join(fields)


def _record(table: DatabaseTable, row: tuple[object, ...]) -> dict[str, Any]:
    cells = row[:-1] if table.kind == "r" else row
    values = {
        column.name: value for column, value in zip(table.columns, cells, strict=True)
    }
    digest = hashlib.sha256(
        json.dumps(
            [table.name, values, row[-1] if table.kind == "r" else None],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    for column in table.columns:
        if column.type_name in {"json", "jsonb"} and values[column.name] is not None:
            # The exact PostgreSQL text is retained, avoiding loss of JSON numeric precision.
            values[column.name] = {"postgresql_json": values[column.name]}
    return {"values": values, "version": "sha256:" + digest}


def _predicate(
    table: DatabaseTable, filters: list[DatabaseFilter]
) -> tuple[sql.Composed, tuple[PostgreSQLAdminParameter, ...]]:
    parts: list[sql.Composable] = []
    parameters: list[PostgreSQLAdminParameter] = []
    operators: dict[str, LiteralString] = {
        "eq": "=",
        "ne": "<>",
        "lt": "<",
        "le": "<=",
        "gt": ">",
        "ge": ">=",
    }
    for item in filters:
        column = table.column(item.field)
        field = sql.Identifier(column.name)
        if item.operator == "is_null" or item.value is None:
            is_null = (
                item.value if item.operator == "is_null" else item.operator == "eq"
            )
            parts.append(
                sql.SQL("{} IS {}NULL").format(
                    field, sql.SQL("" if is_null else "NOT ")
                )
            )
        elif item.operator == "in":
            assert isinstance(item.value, list)
            parts.append(
                sql.SQL("{} IN ({})").format(
                    field, sql.SQL(", ").join(_cast(column) for _ in item.value)
                )
            )
            parameters.extend(_parameter(column, value) for value in item.value)
        else:
            parts.append(
                sql.SQL("{} {} {}").format(
                    field, sql.SQL(operators[item.operator]), _cast(column)
                )
            )
            parameters.append(_parameter(column, item.value))
    return sql.SQL(" AND ").join(parts or [sql.SQL("TRUE")]), tuple(parameters)


def query_table(
    tx: PostgreSQLAdminTransaction, table: DatabaseTable, request: DatabaseQueryRequest
) -> dict[str, Any]:
    for field in request.fields:
        table.column(field)
    where, parameters = _predicate(table, request.filters)
    order: list[sql.Composable] = []
    ordered: set[str] = set()
    for item in request.order:
        table.column(item.field)
        ordered.add(item.field)
        order.append(
            sql.SQL("{} {} NULLS LAST").format(
                sql.Identifier(item.field), sql.SQL(item.direction.upper())
            )
        )
    for key in table.primary_key:
        if key not in ordered:
            order.append(sql.Identifier(key))
    if not order:
        # Read-only views need a deterministic order even without a primary key.
        order.extend(
            sql.SQL("{}::text").format(sql.Identifier(column.name))
            for column in table.columns
        )
    statement = sql.SQL(
        "SELECT {} FROM {} WHERE {} ORDER BY {} LIMIT %s OFFSET %s"
    ).format(_selection(table), _table(table.name), where, sql.SQL(", ").join(order))
    rows = tx.execute(
        _statement(statement), (*parameters, request.limit + 1, request.offset)
    ).fetchall()
    records = [_record(table, row) for row in rows[: request.limit]]
    if request.fields:
        for record in records:
            record["values"] = {
                field: record["values"][field] for field in request.fields
            }
    return {
        "table": table.name,
        "rows": records,
        "next_offset": request.offset + request.limit
        if len(rows) > request.limit
        else None,
        "execution_mode": "read_only",
    }


def change_table(
    tx: PostgreSQLAdminTransaction, table: DatabaseTable, change: DatabaseChange
) -> dict[str, Any]:
    """Apply exactly one row change inside the caller's maintenance transaction."""
    if not table.writable:
        raise DatabaseTableError("ADMIN-DATABASE-READ-ONLY")
    parameters: tuple[PostgreSQLAdminParameter, ...] = ()
    where = sql.SQL("TRUE")
    if change.action != "insert":
        if not table.primary_key or set(change.key) != set(table.primary_key):
            raise DatabaseTableError("ADMIN-DATABASE-PRIMARY-KEY-REQUIRED")
        where, parameters = _predicate(
            table,
            [
                DatabaseFilter(field=field, operator="eq", value=value)
                for field, value in change.key.items()
            ],
        )
        rows = tx.execute(
            _statement(
                sql.SQL("SELECT {} FROM {} WHERE {} FOR UPDATE").format(
                    _selection(table), _table(table.name), where
                )
            ),
            parameters,
        ).fetchall()
        if (
            len(rows) != 1
            or _record(table, rows[0])["version"] != change.expected_version
        ):
            raise DatabaseTableError("ADMIN-DATABASE-VERSION-CONFLICT")
    if change.action == "delete":
        statement = sql.SQL("DELETE FROM {} WHERE {} RETURNING {}").format(
            _table(table.name), where, _selection(table)
        )
    else:
        columns = [table.column(field) for field in change.values]
        if any(column.generated for column in columns):
            raise DatabaseTableError("ADMIN-DATABASE-GENERATED-FIELD")
        values = tuple(
            _parameter(column, change.values[column.name]) for column in columns
        )
        if change.action == "insert":
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
                _table(table.name),
                sql.SQL(", ").join(sql.Identifier(column.name) for column in columns),
                sql.SQL(", ").join(_cast(column) for column in columns),
                _selection(table),
            )
            parameters = values
        else:
            statement = sql.SQL("UPDATE {} SET {} WHERE {} RETURNING {}").format(
                _table(table.name),
                sql.SQL(", ").join(
                    sql.SQL("{} = {}").format(
                        sql.Identifier(column.name), _cast(column)
                    )
                    for column in columns
                ),
                where,
                _selection(table),
            )
            parameters = (*values, *parameters)
    result = tx.execute(_statement(statement), parameters)
    rows = result.fetchall()
    if result.rowcount != 1 or len(rows) != 1:
        raise DatabaseTableError("ADMIN-DATABASE-AFFECTED-COUNT")
    return {
        "table": table.name,
        "action": change.action,
        "affected_count": 1,
        **_record(table, rows[0]),
    }


__all__ = ("DatabaseTableError", "change_table", "query_table", "table_catalog")
