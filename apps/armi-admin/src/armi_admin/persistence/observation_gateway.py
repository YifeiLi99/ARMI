"""Admin observation assembled from owner-authored typed ports."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from armi_artifact_store.api import ArtifactAdminPort
from armi_cognition.api import CognitionAdminPort
from armi_effect.api import EffectAdminPort
from armi_expression.api import ExpressionAdminPort
from armi_interaction.api import InteractionAdminPort
from armi_kernel.application import ArtifactViolation
from armi_material.api import MaterialAdminItem, MaterialAdminReadPort
from armi_mood.api import MoodAdminReadPort
from armi_runtime_foundation import PostgreSQLAdminUnitOfWorkFactory
from armi_subject_state.api import SubjectStateAdminReadPort

from .role_session import AdminRoleBoundPool
from .runtime_foundation import RuntimeFoundationAdminAdapter

_OWNER_BY_KIND = {
    "artifact": "artifact-store",
    "audit_event": "runtime-foundation",
    "effect": "effect",
    "episode": "cognition",
    "operation": "expression",
    "opportunity": "cognition",
    "scene": "interaction",
    "subject": "runtime-foundation",
    "work": "runtime-foundation",
}


def _query_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decode_cursor(cursor: str | None, query_digest: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ADMIN-CURSOR-INVALID") from exc
    if (
        not isinstance(payload, dict)
        or cast(dict[str, object], payload).get("query") != query_digest
        or not isinstance(cast(dict[str, object], payload).get("offset"), int)
        or cast(int, cast(dict[str, object], payload)["offset"]) < 0
    ):
        raise ValueError("ADMIN-CURSOR-MISMATCH")
    return cast(int, cast(dict[str, object], payload)["offset"])


def _encode_cursor(query_digest: str, offset: int) -> str:
    payload = json.dumps(
        {"offset": offset, "query": query_digest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _node(kind: str, identity: object, **attributes: object) -> dict[str, object]:
    return {
        "kind": kind,
        "id": str(identity),
        "owner": _OWNER_BY_KIND[kind],
        "attributes": _safe(attributes),
    }


def _edge(
    kind: str,
    source_kind: str,
    source_id: object,
    target_kind: str,
    target_id: object,
    owner: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "source": {"kind": source_kind, "id": str(source_id)},
        "target": {"kind": target_kind, "id": str(target_id)},
        "owner": owner,
    }


def _safe(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("ADMIN-JSON-NAIVE-DATETIME")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in cast(Mapping[object, object], value).items():
            if not isinstance(key, str):
                raise TypeError("ADMIN-JSON-NONSTRING-KEY")
            result[key] = _safe(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_safe(item) for item in cast(Sequence[object], value)]
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("ADMIN-JSON-BYTES")
    raise TypeError(f"ADMIN-JSON-UNSUPPORTED:{type(value).__qualname__}")


class AdminObservationGateway:
    __slots__ = (
        "_artifacts",
        "_cognition",
        "_effects",
        "_expression",
        "_factory",
        "_interaction",
        "_materials",
        "_mood",
        "_runtime",
        "_subject_state",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLAdminUnitOfWorkFactory,
        runtime: RuntimeFoundationAdminAdapter,
        artifacts: ArtifactAdminPort,
        cognition: CognitionAdminPort,
        effects: EffectAdminPort,
        expression: ExpressionAdminPort,
        interaction: InteractionAdminPort,
        materials: MaterialAdminReadPort,
        mood: MoodAdminReadPort,
        subject_state: SubjectStateAdminReadPort,
    ) -> None:
        self._factory = factory
        self._runtime = runtime
        self._artifacts = artifacts
        self._cognition = cognition
        self._effects = effects
        self._expression = expression
        self._interaction = interaction
        self._materials = materials
        self._mood = mood
        self._subject_state = subject_state

    def environment(self) -> dict[str, object] | None:
        with self._factory.repeatable_read() as uow:
            row = self._runtime.environment(uow.transaction)
        if row is None:
            return None
        return {
            "environment_id": row.environment_id,
            "environment_kind": row.environment_kind,
            "incarnation": row.incarnation,
            "resettable": row.resettable,
            "test_controls_enabled": row.test_controls_enabled,
            "registered_at": _safe(row.registered_at),
        }

    def register_environment(self, values: Mapping[str, object]) -> None:
        with self._factory.serializable() as uow:
            self._runtime.register_environment(
                uow.transaction,
                environment_id=str(values["environment_id"]),
                environment_kind=str(values["environment_kind"]),
                incarnation=int(cast(int, values["incarnation"])),
                resettable=bool(values["resettable"]),
                test_controls_enabled=bool(values["test_controls_enabled"]),
            )
            uow.commit()

    def runtime_status(self) -> dict[str, object]:
        with self._factory.repeatable_read() as uow:
            environment = self._runtime.environment(uow.transaction)
            runtime = self._runtime.latest_runtime(uow.transaction)
        env = (
            None
            if environment is None
            else {
                "environment_id": environment.environment_id,
                "environment_kind": environment.environment_kind,
                "incarnation": environment.incarnation,
                "resettable": environment.resettable,
                "test_controls_enabled": environment.test_controls_enabled,
                "registered_at": _safe(environment.registered_at),
            }
        )
        return {
            "environment": env,
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
        if not isinstance(self._factory, AdminRoleBoundPool):
            raise RuntimeError("ADMIN-DB-CATALOG")
        return self._factory.catalog_digest()

    def subject_snapshot(self, *, private: bool) -> dict[str, object]:
        with self._factory.repeatable_read() as uow:
            tx = uow.transaction
            subject = self._runtime.subject(tx, for_update=False, detailed=True)
            if subject is None:
                return {
                    "subject": None,
                    "components": [],
                    **(
                        {"materials": [], "materials_truncated": False}
                        if private
                        else {}
                    ),
                }
            components = self._subject_state.current_components(tx, private=private)
            mood = self._mood.current_component(tx, private=private)
            material = (
                self._materials.private_snapshot(tx, subject.subject_id)
                if private
                else None
            )
        combined = components if mood is None else (*components, mood)
        result: dict[str, object] = {
            "subject": {
                "subject_id": str(subject.subject_id),
                "subject_version": subject.subject_version,
                "state_epoch": subject.state_epoch,
                "status": subject.status,
                "current_generation_id": str(subject.generation_id),
                "current_bundle_activation_id": None
                if subject.bundle_activation_id is None
                else str(subject.bundle_activation_id),
            },
            "components": [
                {
                    "component_kind": str(item.kind),
                    "component_version": item.version,
                    "privacy_scope": item.privacy_scope,
                    **({"payload": _safe(item.payload)} if private else {}),
                }
                for item in combined
            ],
        }
        if material is not None:
            result["materials"] = [
                self._private_material(item) for item in material.items
            ]
            result["materials_truncated"] = material.truncated
        return result

    @staticmethod
    def _private_material(item: MaterialAdminItem) -> dict[str, object]:
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

    def trace_flow(
        self,
        selector: tuple[str, str],
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        kind, value = selector
        key = UUID(value) if kind != "trace_id" else None
        nodes: list[dict[str, object]] = []
        edges: list[dict[str, object]] = []
        missing: list[dict[str, str]] = []
        with self._factory.repeatable_read() as uow:
            tx = uow.transaction
            if kind == "trace_id":
                rows = self._runtime.audit_trace(tx, trace_id=value)
                for index, row in enumerate(rows):
                    event_id = f"{value}:{index}"
                    nodes.append(
                        _node(
                            "audit_event",
                            event_id,
                            target_kind=row[0],
                            target_ref=row[1],
                            operation=row[2],
                            result_status=row[3],
                            occurred_at=row[4],
                        )
                    )
            elif kind == "episode_id":
                item = self._cognition.episode(tx, episode_id=cast(UUID, key))
                if item is None:
                    missing.append({"kind": "episode", "id": value})
                else:
                    nodes.extend(
                        (
                            _node(
                                "episode",
                                item.episode_id,
                                status=item.status,
                                trace_id=item.trace_id,
                                prepared_at=item.prepared_at,
                            ),
                            _node("opportunity", item.opportunity_id),
                        )
                    )
                    edges.append(
                        _edge(
                            "consumes",
                            "episode",
                            item.episode_id,
                            "opportunity",
                            item.opportunity_id,
                            "cognition",
                        )
                    )
            elif kind == "effect_id":
                item = self._effects.snapshot(tx, effect_id=cast(UUID, key))
                if item is None:
                    missing.append({"kind": "effect", "id": value})
                else:
                    nodes.extend(
                        (
                            _node(
                                "effect",
                                item.effect_id,
                                status=item.status,
                                attempt_id=item.attempt_id,
                            ),
                            _node("operation", item.action_intent_id),
                        )
                    )
                    edges.append(
                        _edge(
                            "realizes",
                            "effect",
                            item.effect_id,
                            "operation",
                            item.action_intent_id,
                            "effect",
                        )
                    )
            else:
                intent = self._expression.operation(tx, operation_ref=cast(UUID, key))
                if intent is None:
                    missing.append({"kind": "operation", "id": value})
                else:
                    nodes.extend(
                        (
                            _node(
                                "operation",
                                intent.operation_ref,
                                action_intent_id=intent.action_intent_id,
                            ),
                            _node("opportunity", intent.root_opportunity_id),
                        )
                    )
                    edges.append(
                        _edge(
                            "originates_from",
                            "operation",
                            intent.operation_ref,
                            "opportunity",
                            intent.root_opportunity_id,
                            "expression",
                        )
                    )
        query = _query_digest({"selector_kind": kind, "selector": value})
        ordered = sorted(
            nodes,
            key=lambda item: (cast(str, item["kind"]), cast(str, item["id"])),
        )
        offset = _decode_cursor(cursor, query)
        page = ordered[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "schema_version": "armi.admin-flow-graph.v1",
            "selector": {"kind": kind, "id": value},
            "nodes": page,
            "edges": sorted(edges, key=lambda item: json.dumps(item, sort_keys=True)),
            "missing": missing,
            "truncated": next_offset < len(ordered),
            "cursor": _encode_cursor(query, next_offset)
            if next_offset < len(ordered)
            else None,
        }

    def diagnostics(self) -> dict[str, object]:
        with self._factory.repeatable_read() as uow:
            runtime = self._runtime.diagnostics(uow.transaction)
            counts = self._artifacts.diagnostic_counts(uow.transaction)
            snapshots = self._artifacts.diagnostic_snapshots(uow.transaction, limit=16)
        # Hash physical objects after closing the database transaction.
        remaining = 32 * 1024 * 1024
        checked: list[dict[str, object]] = []
        for snapshot in snapshots:
            item: dict[str, object] = {
                "artifact_id": str(snapshot.artifact_id),
                "recorded_status": snapshot.integrity_status.value,
            }
            if snapshot.byte_size > remaining:
                item.update(status="not_checked", reason="diagnostic_byte_limit")
            else:
                remaining -= snapshot.byte_size
                try:
                    self._artifacts.read_verified_bytes(snapshot)
                    item["status"] = "verified"
                except ArtifactViolation as error:
                    item.update(status="failed", error_code=error.code)
            checked.append(item)
        return {
            "runtime": _safe(runtime),
            "artifact_integrity": {
                "recorded_counts": dict(counts),
                "physical_checks": checked,
                "coverage": "bounded_sample",
                "max_objects": 16,
                "max_bytes": 32 * 1024 * 1024,
            },
        }

    def inspect_scope(
        self,
        kind: str,
        object_ids: tuple[str, ...],
        *,
        relations: tuple[str, ...],
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        ids = tuple(UUID(value) for value in object_ids)
        with self._factory.repeatable_read() as uow:
            tx = uow.transaction
            if kind == "subject":
                found = self._runtime.inspect_subject_ids(tx, object_ids=ids)
            elif kind == "operation":
                found = self._expression.inspect_ids(tx, object_ids=ids)
            elif kind == "episode":
                found = self._cognition.inspect_ids(tx, object_ids=ids)
            elif kind == "effect":
                found = self._effects.inspect_ids(tx, object_ids=ids)
            elif kind == "work":
                found = self._runtime.inspect_work_ids(tx, object_ids=ids)
            elif kind == "artifact":
                found = self._artifacts.inspect_ids(tx, object_ids=ids)
            else:
                found = self._interaction.inspect_ids(tx, object_ids=ids)
        found_set = set(found)
        nodes = [_node(kind, identity) for identity in sorted(found_set, key=str)]
        missing = [
            {"kind": kind, "id": str(identity)}
            for identity in ids
            if identity not in found_set
        ]
        query = _query_digest(
            {
                "kind": kind,
                "object_ids": list(object_ids),
                "relations": list(relations),
            }
        )
        offset = _decode_cursor(cursor, query)
        page = nodes[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "schema_version": "armi.admin-scope-graph.v1",
            "nodes": page,
            "edges": [],
            "missing": missing,
            "relations": list(relations),
            "truncated": next_offset < len(nodes),
            "cursor": _encode_cursor(query, next_offset)
            if next_offset < len(nodes)
            else None,
        }


__all__ = ("AdminObservationGateway",)
