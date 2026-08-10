"""Fixed Admin observation queries for one role-bound environment."""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from armi_postgresql_contract.catalog_fingerprint import (
    database_catalog_digest,
)
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

    __slots__ = ("_artifact_root", "_conninfo", "_expected_role")

    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        artifact_root: Path,
    ) -> None:
        if not artifact_root.is_absolute() or artifact_root.is_symlink():
            raise ValueError("ADMIN-OBSERVATION-ARTIFACT-ROOT")
        self._conninfo = conninfo
        self._expected_role = expected_role
        self._artifact_root = artifact_root

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
                    "template_digest, data_root_identity_digest, database_identity_digest"
                    ") VALUES (true, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
        rows = self._all(
            "SELECT head.component_kind, head.component_version, "
            "revision.privacy_scope"
            + (", revision.semantic_payload" if private else "")
            + " FROM armi.subject_component_heads AS head "
            "JOIN armi.subject_component_revisions AS revision "
            "ON revision.component_revision_id = head.current_revision_id "
            "ORDER BY head.component_kind"
        )
        component_columns = (
            "component_kind",
            "component_version",
            "privacy_scope",
            *(("payload",) if private else ()),
        )
        result = {
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
        if private:
            material_rows = self._all(
                "SELECT material.life_material_id, material.current_revision_id, "
                "material.material_kind, material.head_version, material.created_at, "
                "material.updated_at, material.deleted_at, revision.revision_no, "
                "revision.title, revision.metadata, revision.material_status, "
                "revision.privacy_status, revision.body_digest, artifact.artifact_id, "
                "artifact.content_digest, artifact.media_type, artifact.byte_size, "
                "artifact.storage_locator, artifact.logical_kind, "
                "artifact.privacy_scope, artifact.integrity_status "
                "FROM armi.life_materials AS material "
                "JOIN armi.life_material_revisions AS revision "
                "ON revision.life_material_revision_id = material.current_revision_id "
                "JOIN armi.artifacts AS artifact "
                "ON artifact.artifact_id = revision.artifact_id "
                "WHERE material.subject_id = %s "
                "ORDER BY material.updated_at DESC, material.life_material_id "
                "LIMIT 101",
                (subject[0],),
            )
            result["materials"] = [
                self._private_material(row) for row in material_rows[:100]
            ]
            result["materials_truncated"] = len(material_rows) > 100
        return result

    def _private_material(self, row: tuple[Any, ...]) -> dict[str, Any]:
        raw_metadata = row[9]
        if type(raw_metadata) is not dict:
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-SHAPE")
        metadata = cast(dict[object, object], raw_metadata)
        if any(
            type(key) is not str or type(value) is not str
            for key, value in metadata.items()
        ):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-SHAPE")
        body = self._read_material_body(row)
        return {
            "material_id": _safe(row[0]),
            "current_revision_id": _safe(row[1]),
            "material_kind": _safe(row[2]),
            "head_version": _safe(row[3]),
            "revision_no": _safe(row[7]),
            "title": _safe(row[8]),
            "body": body,
            "metadata": dict(cast(dict[str, str], raw_metadata)),
            "material_status": _safe(row[10]),
            "privacy_status": _safe(row[11]),
            "body_digest": _safe(row[12]),
            "artifact_id": _safe(row[13]),
            "deleted_at": _safe(row[6]),
            "created_at": _safe(row[4]),
            "updated_at": _safe(row[5]),
        }

    def _read_material_body(self, row: tuple[Any, ...]) -> str:
        content_digest = str(row[14])
        if (
            len(content_digest) != 71
            or not content_digest.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in content_digest[7:]
            )
            or str(row[15]) != "application/json"
            or type(row[16]) is not int
            or not 1 <= row[16] <= 131_072
            or str(row[18]) != "life.material.content"
            or str(row[19]) != "private"
            or str(row[20]) != "verified"
        ):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        digest_hex = content_digest[7:]
        expected_locator = (
            f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
        )
        if str(row[17]) != expected_locator:
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        path = self._artifact_root / Path(expected_locator)
        resolved_root = self._artifact_root.resolve(strict=True)
        root_metadata = self._artifact_root.lstat()
        if (
            self._artifact_root.is_symlink()
            or not self._artifact_root.is_dir()
            or getattr(root_metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        resolved_path = path.resolve(strict=True)
        if not resolved_path.is_relative_to(resolved_root):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        current = path.parent
        while current != self._artifact_root:
            metadata = current.lstat()
            if (
                current.is_symlink()
                or not current.is_dir()
                or getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
            current = current.parent
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or metadata.st_nlink != 1
            or metadata.st_size != row[16]
            or getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        with path.open("rb") as stream:
            artifact_bytes = stream.read(131_073)
        if (
            len(artifact_bytes) != row[16]
            or hashlib.sha256(artifact_bytes).hexdigest() != digest_hex
        ):
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT")
        try:
            decoded: object = json.loads(
                artifact_bytes.decode("utf-8", errors="strict")
            )
            if type(decoded) is not dict:
                raise ValueError
            envelope = cast(dict[str, object], decoded)
            body = envelope.get("body")
            if (
                set(envelope) != {"body", "schema_version"}
                or envelope.get("schema_version") != "armi.life-material-content.v1"
                or type(body) is not str
                or not body.strip()
                or "\x00" in body
                or json.dumps(
                    envelope,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                != artifact_bytes
                or f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
                != str(row[12])
            ):
                raise ValueError
        except UnicodeError, ValueError, json.JSONDecodeError:
            raise ValueError("ADMIN-OBSERVATION-MATERIAL-ARTIFACT") from None
        return body

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
