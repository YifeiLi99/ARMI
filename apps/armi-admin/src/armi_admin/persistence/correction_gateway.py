"""Fixed PostgreSQL gateway for T-07 previews, corrections, and side-work.

The five handlers stay in one module because they share one lock order, preview
digest algorithm, SERIALIZABLE apply boundary, and status reconstruction path.
Splitting them would duplicate the security-critical transaction protocol and
make handler drift harder to detect.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal, cast
from uuid import UUID

import rfc8785
from armi_artifact_store.api import ArtifactAdminPort
from armi_attention.api import OpportunityAdminPort
from armi_codex.api import CodexAdminPort
from armi_cognition.api import CognitionAdminPort
from armi_effect.api import EffectAdminPort
from armi_evidence.api import EvidenceAdminPort
from armi_expression.api import ExpressionAdminPort
from armi_interaction.api import InteractionAdminPort
from armi_material.api import MaterialAdminReadPort
from armi_mood.api import MoodAdminCorrectionPort
from armi_perception.api import PerceptionAdminPort
from armi_prompt.api import PromptAdminReferencePort
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLAdminUnitOfWorkFactory,
)
from armi_subject_state.api import SubjectStateAdminCorrectionPort
from armi_web_observation.api import WebObservationAdminPort

from .role_session import AdminCommitUnknownError, AdminRoleSessionError
from .runtime_foundation import RuntimeFoundationAdminAdapter

CorrectionKind = Literal[
    "delete_uncommitted_creator_input",
    "reconcile_unknown_creator_effect",
    "repair_subject_component_head",
    "replace_subject_component",
    "requeue_stuck_work",
]


class AdminCorrectionGatewayError(RuntimeError):
    """A stable correction failure without SQL, identities, or driver text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _digest(value: object) -> str:
    encoded = rfc8785.dumps(cast(Any, value))
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class AdminCorrectionGateway:
    """Apply only the five versioned S037 correction handlers."""

    __slots__ = (
        "_artifacts",
        "_codex",
        "_cognition",
        "_effects",
        "_environment_id",
        "_evidence",
        "_expression",
        "_factory",
        "_incarnation",
        "_interaction",
        "_material",
        "_mood",
        "_opportunity",
        "_perception",
        "_prompts",
        "_runtime",
        "_subject_state",
        "_web",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLAdminUnitOfWorkFactory,
        runtime: RuntimeFoundationAdminAdapter,
        artifacts: ArtifactAdminPort,
        cognition: CognitionAdminPort,
        codex: CodexAdminPort,
        effects: EffectAdminPort,
        evidence: EvidenceAdminPort,
        expression: ExpressionAdminPort,
        interaction: InteractionAdminPort,
        material: MaterialAdminReadPort,
        opportunity: OpportunityAdminPort,
        perception: PerceptionAdminPort,
        web: WebObservationAdminPort,
        environment_id: str,
        incarnation: int,
        mood: MoodAdminCorrectionPort,
        prompts: PromptAdminReferencePort,
        subject_state: SubjectStateAdminCorrectionPort,
    ) -> None:
        self._factory = factory
        self._runtime = runtime
        self._artifacts = artifacts
        self._cognition = cognition
        self._codex = codex
        self._effects = effects
        self._evidence = evidence
        self._expression = expression
        self._interaction = interaction
        self._material = material
        self._opportunity = opportunity
        self._perception = perception
        self._web = web
        self._environment_id = environment_id
        self._incarnation = incarnation
        self._mood = mood
        self._prompts = prompts
        self._subject_state = subject_state

    def _component_owner(
        self, kind: str
    ) -> SubjectStateAdminCorrectionPort | MoodAdminCorrectionPort:
        return self._mood if kind == "mood" else self._subject_state

    def preview(
        self,
        spec: dict[str, Any],
        *,
        result_id: str,
        side_work_id: str,
    ) -> dict[str, Any]:
        try:
            with self._factory.repeatable_read() as unit_of_work:
                snapshot = self._snapshot(
                    unit_of_work.transaction,
                    spec,
                    result_id=result_id,
                    side_work_id=side_work_id,
                    for_update=False,
                )
                return snapshot
        except AdminCorrectionGatewayError:
            raise
        except AdminRoleSessionError as exc:
            raise AdminCorrectionGatewayError(
                "ADMIN-CORRECTION-PREVIEW-FAILED"
            ) from exc

    def apply(
        self,
        spec: dict[str, Any],
        token: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            with self._factory.serializable() as unit_of_work:
                connection = unit_of_work.transaction
                self._runtime.authority_lock(connection)
                self._fence_expired_authority(connection)
                snapshot = self._snapshot(
                    connection,
                    spec,
                    result_id=str(token["result_id"]),
                    side_work_id=str(token["side_work_id"]),
                    for_update=True,
                )
                if (
                    snapshot["scope_digest"] != token.get("scope_digest")
                    or snapshot["impact_digest"] != token.get("impact_digest")
                    or snapshot["before_digest"] != token.get("before_digest")
                    or snapshot["after_digest"] != token.get("after_digest")
                    or snapshot["subject_version"] != token.get("subject_version")
                    or snapshot["state_epoch"] != token.get("state_epoch")
                ):
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-PREVIEW-STALE")
                handler_result = self._apply_handler(connection, spec, snapshot)
                updated = self._runtime.advance_state_epoch(
                    connection,
                    subject_id=UUID(str(snapshot["subject_id"])),
                    expected=int(snapshot["state_epoch"]),
                )
                if updated is None:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-STATE-EPOCH")
                try:
                    unit_of_work.commit()
                except AdminCommitUnknownError as exc:
                    raise AdminCorrectionGatewayError(
                        "ADMIN-CORRECTION-COMMIT-UNKNOWN"
                    ) from exc
                return {
                    "result_id": token["result_id"],
                    "correction_kind": spec["correction_kind"],
                    "previous_subject_version": snapshot["subject_version"],
                    "subject_version": snapshot["subject_version"],
                    "previous_state_epoch": snapshot["state_epoch"],
                    "state_epoch": updated,
                    "side_work_id": handler_result.get("side_work_id"),
                    "safe_to_restart": True,
                    "status": "applied",
                }
        except AdminCorrectionGatewayError:
            raise
        except AdminRoleSessionError as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-APPLY-FAILED") from exc

    def status(self, spec: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._factory.repeatable_read() as unit_of_work:
                connection = unit_of_work.transaction
                self._environment(connection)
                subject = self._subject(connection, for_update=False)
                current = self._current_target_digest(
                    connection,
                    spec,
                    result_id=str(token["result_id"]),
                    side_work_id=str(token["side_work_id"]),
                )
                base_epoch = int(token["state_epoch"])
                if int(subject[2]) == base_epoch and current == token["before_digest"]:
                    status = "not_applied"
                elif (
                    int(subject[2]) == base_epoch + 1
                    and current == token["after_digest"]
                ):
                    status = "applied"
                elif int(subject[2]) > base_epoch + 1:
                    status = "diverged"
                else:
                    status = "unknown"
                return {
                    "correction_kind": spec["correction_kind"],
                    "result_id": token["result_id"],
                    "status": status,
                    "observed_state_epoch": int(subject[2]),
                    "side_work_id": self._existing_side_work(
                        connection, str(token["side_work_id"])
                    ),
                }
        except AdminCorrectionGatewayError:
            raise
        except AdminRoleSessionError as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-STATUS-FAILED") from exc

    def side_work(self, side_work_id: str) -> dict[str, Any]:
        with self._factory.repeatable_read() as unit_of_work:
            connection = unit_of_work.transaction
            row = self._runtime.side_work(connection, work_id=UUID(side_work_id))
            if row is None:
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-FOUND")
            if row[3] not in {"ready", "completed"}:
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STATE")
            if self._artifacts.snapshot(connection, artifact_id=row[1]) is not None:
                raise AdminCorrectionGatewayError(
                    "ADMIN-CORRECTION-ARTIFACT-REFERENCED"
                )
            return {
                "work_id": str(row[0]),
                "artifact_id": str(row[1]),
                "content_digest": str(row[2]),
                "status": str(row[3]),
            }

    def settle_side_work(
        self, side_work_id: str, content_digest: str
    ) -> dict[str, Any]:
        try:
            with self._factory.serializable() as unit_of_work:
                status = self._runtime.settle_cleanup(
                    unit_of_work.transaction,
                    work_id=UUID(side_work_id),
                    content_digest=content_digest,
                )
                if status is None:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STALE")
                if status == "completed":
                    unit_of_work.commit()
                    return {"side_work_id": side_work_id, "status": "completed"}
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STATE")
        except AdminCorrectionGatewayError:
            raise
        except AdminRoleSessionError as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-FAILED") from exc

    def _snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        result_id: str,
        side_work_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        self._environment(connection)
        subject = self._subject(connection, for_update=for_update)
        detail = self._target_snapshot(
            connection,
            spec,
            subject_id=str(subject[0]),
            result_id=result_id,
            side_work_id=side_work_id,
            for_update=for_update,
        )
        scope = {
            "correction_kind": spec["correction_kind"],
            "subject_id": str(subject[0]),
            "subject_version": int(subject[1]),
            "state_epoch": int(subject[2]),
            "generation_id": str(subject[3]),
            "target_identity": detail["target_identity"],
            "target_versions": detail["target_versions"],
        }
        impact = {
            "correction_kind": spec["correction_kind"],
            "target_count": detail["target_count"],
            "dependency_count": detail["dependency_count"],
            "side_work_required": detail["side_work_required"],
            "before_digest": detail["before_digest"],
            "after_digest": detail["after_digest"],
        }
        status_spec = cast(dict[str, Any], detail["status_spec"])
        status_spec["correction_kind"] = spec["correction_kind"]
        return {
            **detail,
            "result_id": result_id,
            "side_work_id": side_work_id,
            "subject_id": str(subject[0]),
            "subject_version": int(subject[1]),
            "state_epoch": int(subject[2]),
            "generation_id": str(subject[3]),
            "scope_digest": _digest(scope),
            "impact_digest": _digest(impact),
        }

    def _environment(self, connection: PostgreSQLAdminTransaction) -> None:
        row = self._runtime.environment(connection)
        if row is None or row.environment_id != self._environment_id:
            raise AdminCorrectionGatewayError("ADMIN-ENVIRONMENT-MISMATCH")
        if row.incarnation != self._incarnation:
            raise AdminCorrectionGatewayError("ADMIN-ENVIRONMENT-INCARNATION")
        if row.environment_kind not in {"development", "system_test", "acceptance"}:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-ENVIRONMENT-KIND")

    def _subject(
        self, connection: PostgreSQLAdminTransaction, *, for_update: bool
    ) -> tuple[Any, ...]:
        subject = self._runtime.subject(connection, for_update=for_update)
        if subject is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-SUBJECT-UNBORN")
        if for_update and not self._runtime.validate_generation(
            connection, subject.generation_id
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-GENERATION")
        return (
            subject.subject_id,
            subject.subject_version,
            subject.state_epoch,
            subject.generation_id,
        )

    def _fence_expired_authority(self, connection: PostgreSQLAdminTransaction) -> None:
        if not self._runtime.fence_expired_authority(connection):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-RUNTIME-ACTIVE")

    def _target_snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        subject_id: str,
        result_id: str,
        side_work_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        kind = cast(CorrectionKind, spec["correction_kind"])
        if kind in {"replace_subject_component", "repair_subject_component_head"}:
            return self._component_snapshot(
                connection,
                spec,
                subject_id=subject_id,
                result_id=result_id,
                for_update=for_update,
            )
        if kind == "delete_uncommitted_creator_input":
            return self._creator_input_snapshot(
                connection,
                spec,
                subject_id=subject_id,
                side_work_id=side_work_id,
                for_update=for_update,
            )
        if kind == "requeue_stuck_work":
            return self._work_snapshot(connection, spec, for_update=for_update)
        return self._effect_snapshot(
            connection, spec, result_id=result_id, for_update=for_update
        )

    def _component_snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        subject_id: str,
        result_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        owner = self._component_owner(str(spec["component_kind"]))
        head = owner.current_head(
            connection,
            subject_id=subject_id,
            kind=str(spec["component_kind"]),
            for_update=for_update,
        )
        if head is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-COMPONENT-NOT-FOUND")
        if head.current_version != int(spec["expected_component_version"]):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-COMPONENT-VERSION")
        before = _digest(
            {
                "revision_id": str(head.current_revision_id),
                "component_version": head.current_version,
            }
        )
        if spec["correction_kind"] == "replace_subject_component":
            next_version = head.maximum_version + 1
            after = _digest(
                {
                    "revision_id": result_id,
                    "component_version": next_version,
                }
            )
            target = {
                "current_revision_id": str(head.current_revision_id),
                "current_version": head.current_version,
                "next_version": next_version,
            }
        else:
            target_row = owner.revision(
                connection,
                revision_id=str(spec["target_revision_id"]),
                subject_id=subject_id,
                kind=str(spec["component_kind"]),
            )
            if target_row is None:
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-REVISION-NOT-FOUND")
            after = _digest(
                {
                    "revision_id": str(target_row[0]),
                    "component_version": int(target_row[1]),
                }
            )
            target = {
                "current_revision_id": str(head.current_revision_id),
                "current_version": head.current_version,
                "target_revision_id": str(target_row[0]),
                "target_version": int(target_row[1]),
            }
        return {
            "target_identity": _digest(
                {"component_kind": spec["component_kind"], "subject_id": subject_id}
            ),
            "target_versions": {"component": head.current_version},
            "target_count": 1,
            "dependency_count": 2,
            "side_work_required": False,
            "before_digest": before,
            "after_digest": after,
            "handler": target,
            "status_spec": {"component_kind": spec["component_kind"]},
        }

    def _creator_input_snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        subject_id: str,
        side_work_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        interaction = self._interaction.input_snapshot(
            connection, interaction_id=UUID(str(spec["interaction_id"]))
        )
        if interaction is None or str(interaction.subject_id) != subject_id:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-NOT-FOUND")
        evidence = self._evidence.snapshot_for_interaction(
            connection, interaction_id=interaction.interaction_id
        )
        opportunity = (
            None
            if evidence is None
            else self._opportunity.snapshot_for_evidence(
                connection, evidence_id=evidence.evidence_id
            )
        )
        artifact = (
            None
            if evidence is None
            else self._artifacts.snapshot(connection, artifact_id=evidence.artifact_id)
        )
        if evidence is None or opportunity is None or artifact is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-NOT-FOUND")
        if (
            opportunity.disposition != "open"
            or self._cognition.opportunity_consumed(
                connection, opportunity_id=opportunity.opportunity_id
            )
            or self._web.opportunity_consumed(
                connection, opportunity_id=opportunity.opportunity_id
            )
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-COMMITTED")
        shared = self._artifact_has_other_references(
            connection,
            str(evidence.artifact_id),
            excluded_evidence_id=str(evidence.evidence_id),
        )
        audit_count = self._runtime.audit_count(
            connection,
            refs=(
                interaction.interaction_id,
                evidence.evidence_id,
                opportunity.opportunity_id,
            ),
        )
        before = _digest(
            {
                "interaction_id": str(interaction.interaction_id),
                "evidence_id": str(evidence.evidence_id),
                "opportunity_id": str(opportunity.opportunity_id),
                "artifact_id": str(evidence.artifact_id),
                "artifact_shared": shared,
            }
        )
        after = _digest(
            {
                "interaction_absent": True,
                "evidence_absent": True,
                "opportunity_absent": True,
                "artifact_id": str(evidence.artifact_id),
                "artifact_retained": shared,
                "side_work_id": None if shared else side_work_id,
            }
        )
        return {
            "target_identity": _digest(
                {"interaction_id": str(interaction.interaction_id)}
            ),
            "target_versions": {"input_chain": 1},
            "target_count": 4 + audit_count,
            "dependency_count": 3,
            "side_work_required": not shared,
            "before_digest": before,
            "after_digest": after,
            "handler": {
                "interaction_id": str(interaction.interaction_id),
                "evidence_id": str(evidence.evidence_id),
                "opportunity_id": str(opportunity.opportunity_id),
                "artifact_id": str(evidence.artifact_id),
                "content_digest": artifact.content_digest,
                "artifact_shared": shared,
                "audit_count": audit_count,
                "side_work_id": side_work_id,
            },
            "status_spec": {
                "interaction_id": str(interaction.interaction_id),
                "evidence_id": str(evidence.evidence_id),
                "opportunity_id": str(opportunity.opportunity_id),
                "artifact_id": str(evidence.artifact_id),
                "artifact_shared": shared,
            },
        }

    def _work_snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        for_update: bool,
    ) -> dict[str, Any]:
        work = self._runtime.work(
            connection, work_id=UUID(str(spec["work_id"])), for_update=for_update
        )
        if work is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-FOUND")
        if not self._runtime.work_is_stuck(connection, work):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-STUCK")
        before = _digest(
            {
                "work_id": str(work.work_id),
                "status": work.status,
                "lease_token": work.lease_token,
            }
        )
        after = _digest(
            {
                "work_id": str(work.work_id),
                "status": "ready",
                "lease_token": work.lease_token + 1,
            }
        )
        return {
            "target_identity": _digest({"work_id": str(work.work_id)}),
            "target_versions": {"lease_token": work.lease_token},
            "target_count": 1,
            "dependency_count": 1,
            "side_work_required": False,
            "before_digest": before,
            "after_digest": after,
            "handler": {"work_id": str(work.work_id), "lease_token": work.lease_token},
            "status_spec": {"work_id": str(work.work_id)},
        }

    def _effect_snapshot(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        *,
        result_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        effect = self._effects.snapshot(
            connection, effect_id=UUID(str(spec["effect_id"])), for_update=for_update
        )
        if effect is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-NOT-FOUND")
        if effect.status != "unknown" or effect.attempt_id is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-NOT-UNKNOWN")
        intent = self._expression.intent(
            connection, action_intent_id=effect.action_intent_id
        )
        if intent is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-NOT-FOUND")
        completed = effect.delivery_id is not None
        result_status = "completed" if completed else "failed"
        observation_digest = _digest(
            {
                "effect_id": str(effect.effect_id),
                "delivery_id": None
                if effect.delivery_id is None
                else str(effect.delivery_id),
                "receipt_digest": effect.receipt_digest,
                "result": result_status,
            }
        )
        before = _digest(
            {
                "effect_id": str(effect.effect_id),
                "status": effect.status,
                "attempt_id": str(effect.attempt_id),
            }
        )
        after = _digest(
            {
                "effect_id": str(effect.effect_id),
                "status": result_status,
                "observation_id": result_id,
                "observation_digest": observation_digest,
            }
        )
        return {
            "target_identity": _digest({"effect_id": str(effect.effect_id)}),
            "target_versions": {"effect_state": "unknown"},
            "target_count": 3,
            "dependency_count": 2,
            "side_work_required": False,
            "before_digest": before,
            "after_digest": after,
            "handler": {
                "effect_id": str(effect.effect_id),
                "attempt_id": str(effect.attempt_id),
                "operation_ref": str(intent.operation_ref),
                "outbox_id": str(effect.outbox_id),
                "delivery_id": None
                if effect.delivery_id is None
                else str(effect.delivery_id),
                "observation_id": result_id,
                "observation_digest": observation_digest,
                "result_status": result_status,
            },
            "status_spec": {"effect_id": str(effect.effect_id)},
        }

    def _apply_handler(
        self,
        connection: PostgreSQLAdminTransaction,
        spec: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        kind = cast(CorrectionKind, spec["correction_kind"])
        handler = cast(dict[str, Any], snapshot["handler"])
        if kind == "replace_subject_component":
            owner = self._component_owner(str(spec["component_kind"]))
            if not owner.replace(
                connection,
                revision_id=str(snapshot["result_id"]),
                subject_id=str(snapshot["subject_id"]),
                kind=str(spec["component_kind"]),
                version=int(handler["next_version"]),
                previous_revision_id=str(handler["current_revision_id"]),
                replacement=spec["replacement"],
            ):
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-COMPONENT-CAS")
        elif kind == "repair_subject_component_head":
            owner = self._component_owner(str(spec["component_kind"]))
            if not owner.repair_head(
                connection,
                subject_id=str(snapshot["subject_id"]),
                kind=str(spec["component_kind"]),
                current_revision_id=str(handler["current_revision_id"]),
                current_version=int(handler["current_version"]),
                target_revision_id=str(handler["target_revision_id"]),
                target_version=int(handler["target_version"]),
            ):
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-COMPONENT-CAS")
        elif kind == "delete_uncommitted_creator_input":
            self._delete_input(connection, snapshot, handler)
        elif kind == "requeue_stuck_work":
            if not self._runtime.requeue(
                connection,
                work_id=UUID(str(handler["work_id"])),
                lease_token=int(handler["lease_token"]),
            ):
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-CAS")
        elif kind == "reconcile_unknown_creator_effect":
            self._reconcile_effect(connection, handler)
        return {
            "side_work_id": handler.get("side_work_id")
            if snapshot["side_work_required"]
            else None
        }

    def _delete_input(
        self,
        connection: PostgreSQLAdminTransaction,
        snapshot: dict[str, Any],
        handler: dict[str, Any],
    ) -> None:
        ids = (
            UUID(str(handler["interaction_id"])),
            UUID(str(handler["evidence_id"])),
            UUID(str(handler["opportunity_id"])),
        )
        self._runtime.delete_audit(connection, refs=ids)
        if not self._opportunity.delete_open(connection, opportunity_id=ids[2]):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-CAS")
        self._evidence.delete(connection, evidence_id=ids[1])
        self._interaction.delete_input_chain(connection, interaction_id=ids[0])
        if not handler["artifact_shared"]:
            if not self._artifacts.delete(
                connection, artifact_id=UUID(str(handler["artifact_id"]))
            ):
                raise AdminCorrectionGatewayError(
                    "ADMIN-CORRECTION-ARTIFACT-REFERENCED"
                )
            self._runtime.create_cleanup_work(
                connection,
                work_id=UUID(str(handler["side_work_id"])),
                result_id=UUID(str(snapshot["result_id"])),
                subject_id=UUID(str(snapshot["subject_id"])),
                artifact_id=UUID(str(handler["artifact_id"])),
                content_digest=str(handler["content_digest"]),
            )

    def _reconcile_effect(
        self, connection: PostgreSQLAdminTransaction, handler: dict[str, Any]
    ) -> None:
        completed = handler["result_status"] == "completed"
        snapshot = self._effects.snapshot(
            connection, effect_id=UUID(str(handler["effect_id"])), for_update=True
        )
        if snapshot is None or not self._effects.reconcile(
            connection,
            snapshot=snapshot,
            observation_id=UUID(str(handler["observation_id"])),
            observation_digest=str(handler["observation_digest"]),
            completed=completed,
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-OUTBOX")

    def _current_target_digest(
        self,
        connection: PostgreSQLAdminTransaction,
        status_spec: dict[str, Any],
        *,
        result_id: str,
        side_work_id: str,
    ) -> str:
        kind = status_spec["correction_kind"]
        if kind in {"replace_subject_component", "repair_subject_component_head"}:
            owner = self._component_owner(str(status_spec["component_kind"]))
            row = owner.find_current(
                connection, kind=str(status_spec["component_kind"])
            )
            if row is None:
                return _digest({"missing": True})
            return _digest(
                {
                    "revision_id": str(row[0]),
                    "component_version": int(row[1]),
                }
            )
        if kind == "delete_uncommitted_creator_input":
            interaction = self._interaction.input_snapshot(
                connection, interaction_id=UUID(str(status_spec["interaction_id"]))
            )
            evidence = (
                None
                if interaction is None
                else self._evidence.snapshot_for_interaction(
                    connection, interaction_id=interaction.interaction_id
                )
            )
            opportunity = (
                None
                if evidence is None
                else self._opportunity.snapshot_for_evidence(
                    connection, evidence_id=evidence.evidence_id
                )
            )
            if interaction is None:
                work = self._existing_side_work(connection, side_work_id)
                return _digest(
                    {
                        "interaction_absent": True,
                        "evidence_absent": True,
                        "opportunity_absent": True,
                        "artifact_id": status_spec["artifact_id"],
                        "artifact_retained": bool(status_spec["artifact_shared"]),
                        "side_work_id": None
                        if status_spec["artifact_shared"]
                        else work,
                    }
                )
            return _digest(
                {
                    "interaction_id": status_spec["interaction_id"],
                    "evidence_id": None
                    if evidence is None
                    else str(evidence.evidence_id),
                    "opportunity_id": None
                    if opportunity is None
                    else str(opportunity.opportunity_id),
                    "artifact_id": None
                    if evidence is None
                    else str(evidence.artifact_id),
                    "artifact_shared": bool(status_spec["artifact_shared"]),
                }
            )
        if kind == "requeue_stuck_work":
            row = self._runtime.work_state(
                connection, work_id=UUID(str(status_spec["work_id"]))
            )
            return (
                _digest(
                    {
                        "work_id": status_spec["work_id"],
                        "status": row[0],
                        "lease_token": int(row[1]),
                    }
                )
                if row is not None
                else _digest({"missing": True})
            )
        row = self._effects.current_state(
            connection, effect_id=UUID(str(status_spec["effect_id"]))
        )
        if row is None:
            return _digest({"missing": True})
        return _digest(
            {
                "effect_id": status_spec["effect_id"],
                "status": str(row[0]),
                "observation_id": None if row[1] is None else str(row[1]),
                "observation_digest": None if row[2] is None else row[2],
            }
        )

    def _existing_side_work(
        self, connection: PostgreSQLAdminTransaction, side_work_id: str
    ) -> str | None:
        row = self._runtime.existing_cleanup_work(
            connection, work_id=UUID(side_work_id)
        )
        return None if row is None else str(row)

    def _artifact_has_other_references(
        self,
        connection: PostgreSQLAdminTransaction,
        artifact_id: str,
        *,
        excluded_evidence_id: str,
    ) -> bool:
        artifact_uuid = UUID(artifact_id)
        if self._prompts.references_artifact(connection, artifact_id=artifact_id):
            return True
        return any(
            (
                self._runtime.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._interaction.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                int(
                    self._material.references_artifact(
                        connection, artifact_id=artifact_uuid
                    )
                ),
                self._perception.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._evidence.artifact_reference_count(
                    connection,
                    artifact_id=artifact_uuid,
                    excluded_evidence_id=UUID(excluded_evidence_id),
                ),
                self._cognition.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._expression.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._effects.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._web.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
                self._codex.artifact_reference_count(
                    connection, artifact_id=artifact_uuid
                ),
            )
        )


__all__ = ("AdminCorrectionGateway", "AdminCorrectionGatewayError")
