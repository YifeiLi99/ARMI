"""Fixed Admin observation queries for one role-bound environment."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from armi_material.api import MaterialAdminItem, MaterialAdminReadPort
from armi_mood.api import MoodAdminReadPort
from armi_postgresql_contract.catalog_fingerprint import (
    database_catalog_digest,
)
from armi_subject_state.api import SubjectStateAdminReadPort
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

    __slots__ = ("_conninfo", "_expected_role", "_materials", "_mood", "_subject_state")

    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        materials: MaterialAdminReadPort,
        mood: MoodAdminReadPort,
        subject_state: SubjectStateAdminReadPort,
    ) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role
        self._materials = materials
        self._mood = mood
        self._subject_state = subject_state

    def environment(self) -> dict[str, Any] | None:
        row = self._one(
            "SELECT environment_id, environment_kind, incarnation, resettable, "
            "test_controls_enabled, registered_at "
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
                    "resettable, test_controls_enabled"
                    ") VALUES (true, %s, %s, %s, %s, %s)",
                    (
                        values["environment_id"],
                        values["environment_kind"],
                        values["incarnation"],
                        values["resettable"],
                        values["test_controls_enabled"],
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
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                return database_catalog_digest(connection)
        finally:
            pool.close()

    def subject_snapshot(self, *, private: bool) -> dict[str, Any]:
        subject = self._one(
            "SELECT subject_id, subject_version, state_epoch, status, "
            "current_generation_id, current_bundle_activation_id "
            "FROM armi.subjects WHERE singleton_key"
        )
        if subject is None:
            result: dict[str, Any] = {"subject": None, "components": []}
            if private:
                result.update({"materials": [], "materials_truncated": False})
            return result
        columns = (
            "subject_id",
            "subject_version",
            "state_epoch",
            "status",
            "current_generation_id",
            "current_bundle_activation_id",
        )
        subject_components = self._subject_state.current_components(private=private)
        mood = self._mood.current_component(private=private)
        components = subject_components if mood is None else (*subject_components, mood)
        result = {
            "subject": dict(
                zip(columns, (_safe(value) for value in subject), strict=True)
            ),
            "components": [
                {
                    "component_kind": str(item.kind),
                    "component_version": item.version,
                    "privacy_scope": item.privacy_scope,
                    **({"payload": _safe(item.payload)} if private else {}),
                }
                for item in components
            ],
        }
        if private:
            snapshot = self._materials.private_snapshot(UUID(str(subject[0])))
            result["materials"] = [
                self._private_material(item) for item in snapshot.items
            ]
            result["materials_truncated"] = snapshot.truncated
        return result

    def _private_material(self, item: MaterialAdminItem) -> dict[str, Any]:
        return {
            "material_id": _safe(item.material_id),
            "current_revision_id": _safe(item.current_revision_id),
            "material_kind": _safe(item.material_kind),
            "head_version": item.head_version,
            "revision_no": item.revision_no,
            "title": item.title,
            "body": item.body,
            "metadata": dict(item.metadata),
            "material_status": _safe(item.material_status),
            "privacy_status": _safe(item.privacy_status),
            "artifact_id": _safe(item.artifact_id),
            "deleted_at": _safe(item.deleted_at),
            "created_at": _safe(item.created_at),
            "updated_at": _safe(item.updated_at),
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
                "SELECT operation_id, root_opportunity_id, current_status, "
                "effect_id, completed_at FROM armi.action_operations "
                "WHERE operation_id = %s OR root_opportunity_id = %s LIMIT 200",
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
                "action_operations",
                "operation_id",
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
