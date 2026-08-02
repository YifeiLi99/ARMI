"""Fixed Admin observation queries for one role-bound environment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from psycopg import sql
from psycopg.abc import QueryNoTemplate

from .role_session import AdminRoleBoundPool


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (UUID, datetime, date, Decimal)):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_safe(item) for item in cast(Sequence[object], value)]
    return str(value)


class AdminObservationGateway:
    """Execute only static, bounded SELECT and environment registration statements."""

    __slots__ = ("_conninfo", "_expected_role")

    def __init__(self, conninfo: str, *, expected_role: str) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role

    def environment(self) -> dict[str, Any] | None:
        row = self._one(
            "SELECT environment_id, environment_kind, incarnation, resettable, "
            "test_controls_enabled, bundle_digest, config_digest, template_digest, "
            "data_root_identity_digest, database_identity_digest, registered_at "
            "FROM armi.deployment_environments WHERE singleton_key"
        )
        if row is None:
            return None
        names = (
            "environment_id",
            "environment_kind",
            "incarnation",
            "resettable",
            "test_controls_enabled",
            "bundle_digest",
            "config_digest",
            "template_digest",
            "data_root_identity_digest",
            "database_identity_digest",
            "registered_at",
        )
        return dict(zip(names, (_safe(value) for value in row), strict=True))

    def register_environment(self, values: dict[str, Any]) -> None:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.execute(
                    "INSERT INTO armi.deployment_environments ("
                    "singleton_key, environment_id, environment_kind, incarnation, "
                    "resettable, test_controls_enabled, bundle_digest, config_digest, "
                    "template_digest, data_root_identity_digest, database_identity_digest, "
                    "schema_version) VALUES (true, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
                    (
                        values["environment_id"],
                        values["environment_kind"],
                        values["incarnation"],
                        values["resettable"],
                        values["test_controls_enabled"],
                        values["bundle_digest"],
                        values["config_digest"],
                        values["template_digest"],
                        values["data_root_identity_digest"],
                        values["database_identity_digest"],
                    ),
                )
                connection.commit()
        finally:
            pool.close()

    def runtime_status(self) -> dict[str, Any]:
        environment = self.environment()
        runtime = self._one(
            "SELECT runtime_instance_id, life_generation_id, fence_token, status, "
            "last_heartbeat_at, lease_expires_at FROM armi.runtime_instances "
            "ORDER BY started_at DESC, runtime_instance_id DESC LIMIT 1"
        )
        return {
            "environment": environment,
            "runtime": None
            if runtime is None
            else dict(
                zip(
                    (
                        "runtime_instance_id",
                        "life_generation_id",
                        "fence_token",
                        "status",
                        "last_heartbeat_at",
                        "lease_expires_at",
                    ),
                    (_safe(value) for value in runtime),
                    strict=True,
                )
            ),
        }

    def database_catalog_digest(self) -> str:
        rows = self._all(
            "SELECT relation.relname, relation.relkind, attribute.attname, "
            "pg_catalog.format_type(attribute.atttypid, attribute.atttypmod), "
            "attribute.attnotnull "
            "FROM pg_catalog.pg_class AS relation "
            "JOIN pg_catalog.pg_namespace AS namespace "
            "ON namespace.oid = relation.relnamespace "
            "LEFT JOIN pg_catalog.pg_attribute AS attribute "
            "ON attribute.attrelid = relation.oid AND attribute.attnum > 0 "
            "AND NOT attribute.attisdropped "
            "WHERE namespace.nspname = 'armi' AND relation.relkind = 'r' "
            "ORDER BY relation.relname, attribute.attnum"
        )
        encoded = json.dumps(
            [[_safe(value) for value in row] for row in rows],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def subject_snapshot(self, *, private: bool) -> dict[str, Any]:
        subject = self._one(
            "SELECT subject_id, subject_version, state_epoch, status, "
            "current_generation_id, current_bundle_activation_id "
            "FROM armi.subjects WHERE singleton_key"
        )
        if subject is None:
            return {"subject": None, "components": []}
        columns = (
            "subject_id",
            "subject_version",
            "state_epoch",
            "status",
            "current_generation_id",
            "current_bundle_activation_id",
        )
        rows = self._all(
            "SELECT head.component_kind, head.component_version, "
            "revision.semantic_digest, revision.privacy_scope"
            + (", revision.semantic_payload" if private else "")
            + " FROM armi.subject_component_heads AS head "
            "JOIN armi.subject_component_revisions AS revision "
            "ON revision.component_revision_id = head.current_revision_id "
            "ORDER BY head.component_kind"
        )
        component_columns = (
            "component_kind",
            "component_version",
            "semantic_digest",
            "privacy_scope",
            *(("payload",) if private else ()),
        )
        return {
            "subject": dict(
                zip(columns, (_safe(value) for value in subject), strict=True)
            ),
            "components": [
                dict(
                    zip(component_columns, (_safe(value) for value in row), strict=True)
                )
                for row in rows
            ],
        }

    def trace_flow(self, selector: tuple[str, str]) -> dict[str, Any]:
        kind, value = selector
        if kind == "trace_id":
            rows = self._all(
                "SELECT target_kind, target_ref, operation, result_status, occurred_at "
                "FROM armi.audit_events WHERE trace_id = %s "
                "ORDER BY occurred_at, audit_event_id LIMIT 200",
                (value,),
            )
        elif kind == "episode_id":
            rows = self._all(
                "SELECT cognitive_episode_id, opportunity_id, status, trace_id, prepared_at "
                "FROM armi.cognitive_episodes WHERE cognitive_episode_id = %s",
                (value,),
            )
        elif kind == "effect_id":
            rows = self._all(
                "SELECT effect_id, status, verification_status, current_attempt_id, settled_at "
                "FROM armi.effects WHERE effect_id = %s",
                (value,),
            )
        else:
            rows = self._all(
                "SELECT creator_response_operation_id, root_opportunity_id, current_status, "
                "effect_id, completed_at FROM armi.creator_response_operations "
                "WHERE creator_response_operation_id = %s OR root_opportunity_id = %s LIMIT 200",
                (value, value),
            )
        return {
            "selector_kind": kind,
            "items": [[_safe(value) for value in row] for row in rows],
        }

    def inspect_scope(self, kind: str, object_ids: tuple[str, ...]) -> dict[str, Any]:
        mapping = {
            "subject": ("subjects", "subject_id"),
            "operation": (
                "creator_response_operations",
                "creator_response_operation_id",
            ),
            "episode": ("cognitive_episodes", "cognitive_episode_id"),
            "effect": ("effects", "effect_id"),
            "work": ("durable_work", "work_id"),
            "artifact": ("artifacts", "artifact_id"),
            "scene": ("interaction_scenes", "scene_id"),
        }
        table, column = mapping[kind]
        statement = sql.SQL(
            "SELECT {column} FROM armi.{table} "
            "WHERE {column} = ANY(%s::uuid[]) ORDER BY {column}"
        ).format(column=sql.Identifier(column), table=sql.Identifier(table))
        rows = self._all(
            statement,
            (list(object_ids),),
        )
        found = [str(row[0]) for row in rows]
        return {
            "kind": kind,
            "found_ids": found,
            "missing_count": len(object_ids) - len(found),
        }

    def _pool(self) -> AdminRoleBoundPool:
        return AdminRoleBoundPool(self._conninfo, expected_role=self._expected_role)

    def _one(
        self, statement: QueryNoTemplate, parameters: tuple[Any, ...] = ()
    ) -> tuple[Any, ...] | None:
        rows = self._all(statement, parameters)
        return rows[0] if rows else None

    def _all(
        self, statement: QueryNoTemplate, parameters: tuple[Any, ...] = ()
    ) -> list[tuple[Any, ...]]:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                return connection.execute(statement, parameters).fetchall()
        finally:
            pool.close()


__all__ = ("AdminObservationGateway",)
