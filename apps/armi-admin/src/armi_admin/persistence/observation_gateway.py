"""Admin observation assembled from owner-authored typed ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from armi_artifact_store.api import ArtifactAdminPort
from armi_cognition.api import CognitionAdminPort
from armi_effect.api import EffectAdminPort
from armi_expression.api import ExpressionAdminPort
from armi_interaction.api import InteractionAdminPort
from armi_material.api import MaterialAdminItem, MaterialAdminReadPort
from armi_mood.api import MoodAdminReadPort
from armi_runtime_foundation import PostgreSQLAdminUnitOfWorkFactory
from armi_subject_state.api import SubjectStateAdminReadPort

from .role_session import AdminRoleBoundPool
from .runtime_foundation import RuntimeFoundationAdminAdapter


def _safe(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (UUID, datetime, date, Decimal)):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_safe(item) for item in cast(Sequence[object], value)]
    return str(value)


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

    def trace_flow(self, selector: tuple[str, str]) -> dict[str, object]:
        kind, value = selector
        key = UUID(value) if kind != "trace_id" else None
        with self._factory.repeatable_read() as uow:
            tx = uow.transaction
            if kind == "trace_id":
                rows = self._runtime.audit_trace(tx, trace_id=value)
            elif kind == "episode_id":
                item = self._cognition.episode(tx, episode_id=cast(UUID, key))
                rows = (
                    ()
                    if item is None
                    else (
                        (
                            item.episode_id,
                            item.opportunity_id,
                            item.status,
                            item.trace_id,
                            item.prepared_at,
                        ),
                    )
                )
            elif kind == "effect_id":
                item = self._effects.snapshot(tx, effect_id=cast(UUID, key))
                rows = (
                    ()
                    if item is None
                    else ((item.effect_id, item.status, item.attempt_id),)
                )
            else:
                intent = self._expression.operation(tx, operation_ref=cast(UUID, key))
                rows = (
                    ()
                    if intent is None
                    else ((intent.operation_ref, intent.root_opportunity_id),)
                )
        return {
            "selector_kind": kind,
            "items": [[_safe(value) for value in row] for row in rows],
        }

    def inspect_scope(
        self, kind: str, object_ids: tuple[str, ...]
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
        return {
            "kind": kind,
            "found_ids": [str(value) for value in found],
            "missing_count": len(ids) - len(found),
        }


__all__ = ("AdminObservationGateway",)
