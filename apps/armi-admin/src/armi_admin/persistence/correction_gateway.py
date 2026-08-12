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

import psycopg
import rfc8785
from armi_mood.api import MoodAdminCorrectionPort
from armi_subject_state.api import SubjectStateAdminCorrectionPort
from psycopg_pool import PoolTimeout

from .role_session import AdminRoleBoundPool, AdminRoleSessionError

_AUTHORITY_KEY_PREFIX = "armi.runtime-authority:"
CorrectionKind = Literal[
    "delete_uncommitted_creator_input",
    "reconcile_unknown_creator_effect",
    "repair_subject_component_head",
    "replace_subject_component",
    "requeue_stuck_work",
]


class AdminCorrectionGatewayError(RuntimeError):
    """A stable correction failure without SQL, identities, or driver text."""


def _digest(value: object) -> str:
    encoded = rfc8785.dumps(cast(Any, value))
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class AdminCorrectionGateway:
    """Apply only the five versioned S037 correction handlers."""

    __slots__ = (
        "_conninfo",
        "_environment_id",
        "_expected_role",
        "_incarnation",
        "_mood",
        "_subject_state",
    )

    def __init__(
        self,
        conninfo: str,
        *,
        expected_role: str,
        environment_id: str,
        incarnation: int,
        mood: MoodAdminCorrectionPort,
        subject_state: SubjectStateAdminCorrectionPort,
    ) -> None:
        self._conninfo = conninfo
        self._expected_role = expected_role
        self._environment_id = environment_id
        self._incarnation = incarnation
        self._mood = mood
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
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.commit()
                connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                snapshot = self._snapshot(
                    connection,
                    spec,
                    result_id=result_id,
                    side_work_id=side_work_id,
                    for_update=False,
                )
                connection.commit()
                return snapshot
        except AdminCorrectionGatewayError:
            raise
        except (psycopg.Error, PoolTimeout, AdminRoleSessionError) as exc:
            raise AdminCorrectionGatewayError(
                "ADMIN-CORRECTION-PREVIEW-FAILED"
            ) from exc
        finally:
            pool.close()

    def apply(
        self,
        spec: dict[str, Any],
        token: dict[str, Any],
    ) -> dict[str, Any]:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.commit()
                connection.execute(
                    "SELECT pg_catalog.pg_advisory_lock("
                    "pg_catalog.hashtextextended(%s, 0))",
                    (_AUTHORITY_KEY_PREFIX + self._environment_id,),
                )
                connection.commit()
                connection.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
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
                updated = connection.execute(
                    "UPDATE armi.subjects SET state_epoch = state_epoch + 1 "
                    "WHERE subject_id = %s AND state_epoch = %s RETURNING state_epoch",
                    (snapshot["subject_id"], snapshot["state_epoch"]),
                ).fetchone()
                if updated is None:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-STATE-EPOCH")
                try:
                    connection.commit()
                except psycopg.OperationalError as exc:
                    raise AdminCorrectionGatewayError(
                        "ADMIN-CORRECTION-COMMIT-UNKNOWN"
                    ) from exc
                return {
                    "result_id": token["result_id"],
                    "correction_kind": spec["correction_kind"],
                    "previous_subject_version": snapshot["subject_version"],
                    "subject_version": snapshot["subject_version"],
                    "previous_state_epoch": snapshot["state_epoch"],
                    "state_epoch": int(updated[0]),
                    "side_work_id": handler_result.get("side_work_id"),
                    "safe_to_restart": True,
                    "status": "applied",
                }
        except AdminCorrectionGatewayError:
            raise
        except (psycopg.Error, PoolTimeout, AdminRoleSessionError) as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-APPLY-FAILED") from exc
        finally:
            pool.close()

    def status(self, spec: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.execute("SET TRANSACTION READ ONLY")
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
        except (psycopg.Error, PoolTimeout, AdminRoleSessionError) as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-STATUS-FAILED") from exc
        finally:
            pool.close()

    def side_work(self, side_work_id: str) -> dict[str, Any]:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                row = connection.execute(
                    "SELECT work_id, payload_ref, payload_digest, status, "
                    "deadline_at FROM armi.durable_work "
                    "WHERE work_id = %s "
                    "AND work_kind = 'admin.correction.artifact-cleanup' "
                    "AND owner_kind = 'admin_correction'",
                    (side_work_id,),
                ).fetchone()
                if row is None:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-FOUND")
                if row[3] not in {"ready", "completed"}:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STATE")
                artifact_exists = connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM armi.artifacts WHERE artifact_id = %s)",
                    (row[1],),
                ).fetchone()
                if artifact_exists is None or bool(artifact_exists[0]):
                    raise AdminCorrectionGatewayError(
                        "ADMIN-CORRECTION-ARTIFACT-REFERENCED"
                    )
                return {
                    "work_id": str(row[0]),
                    "artifact_id": str(row[1]),
                    "content_digest": str(row[2]),
                    "status": str(row[3]),
                }
        finally:
            pool.close()

    def settle_side_work(
        self, side_work_id: str, content_digest: str
    ) -> dict[str, Any]:
        pool = self._pool()
        try:
            pool.open()
            with pool.connection() as connection:
                row = connection.execute(
                    "SELECT status, payload_digest FROM armi.durable_work "
                    "WHERE work_id = %s "
                    "AND work_kind = 'admin.correction.artifact-cleanup' FOR UPDATE",
                    (side_work_id,),
                ).fetchone()
                if row is None or str(row[1]) != content_digest:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STALE")
                if row[0] == "completed":
                    return {"side_work_id": side_work_id, "status": "completed"}
                if row[0] != "ready":
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STATE")
                updated = connection.execute(
                    "UPDATE armi.durable_work SET status = 'completed', "
                    "result_kind = 'artifact_cleanup', result_ref = work_id, "
                    "last_error_code = NULL, updated_at = statement_timestamp() "
                    "WHERE work_id = %s AND status = 'ready'",
                    (side_work_id,),
                ).rowcount
                if updated != 1:
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-STALE")
                connection.commit()
                return {"side_work_id": side_work_id, "status": "completed"}
        except AdminCorrectionGatewayError:
            raise
        except (psycopg.Error, PoolTimeout, AdminRoleSessionError) as exc:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-FAILED") from exc
        finally:
            pool.close()

    def _snapshot(
        self,
        connection: psycopg.Connection[Any],
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

    def _environment(self, connection: psycopg.Connection[Any]) -> None:
        row = connection.execute(
            "SELECT environment_id, environment_kind, incarnation "
            "FROM armi.deployment_environments WHERE singleton_key"
        ).fetchone()
        if row is None or str(row[0]) != self._environment_id:
            raise AdminCorrectionGatewayError("ADMIN-ENVIRONMENT-MISMATCH")
        if int(row[2]) != self._incarnation:
            raise AdminCorrectionGatewayError("ADMIN-ENVIRONMENT-INCARNATION")
        if str(row[1]) not in {"development", "system_test", "acceptance"}:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-ENVIRONMENT-KIND")

    @staticmethod
    def _subject(
        connection: psycopg.Connection[Any], *, for_update: bool
    ) -> tuple[Any, ...]:
        suffix = " FOR UPDATE" if for_update else ""
        row = connection.execute(
            "SELECT subject_id, subject_version, state_epoch, current_generation_id "
            "FROM armi.subjects WHERE singleton_key = 1" + suffix
        ).fetchone()
        if row is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-SUBJECT-UNBORN")
        if for_update:
            generation = connection.execute(
                "SELECT life_generation_id FROM armi.life_generations "
                "WHERE life_generation_id = %s",
                (row[3],),
            ).fetchone()
            if generation is None:
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-GENERATION")
        return row

    @staticmethod
    def _fence_expired_authority(connection: psycopg.Connection[Any]) -> None:
        rows = connection.execute(
            "SELECT runtime_instance_id, status, lease_expires_at "
            "FROM armi.runtime_instances ORDER BY started_at, runtime_instance_id FOR UPDATE"
        ).fetchall()
        for row in rows:
            if row[1] == "active":
                current = connection.execute(
                    "SELECT %s > statement_timestamp()", (row[2],)
                ).fetchone()
                if current is not None and bool(current[0]):
                    raise AdminCorrectionGatewayError("ADMIN-CORRECTION-RUNTIME-ACTIVE")
                connection.execute(
                    "UPDATE armi.runtime_instances SET status = 'fenced', "
                    "stopped_at = statement_timestamp() "
                    "WHERE runtime_instance_id = %s AND status = 'active'",
                    (row[0],),
                )

    def _target_snapshot(
        self,
        connection: psycopg.Connection[Any],
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
        connection: psycopg.Connection[Any],
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
        connection: psycopg.Connection[Any],
        spec: dict[str, Any],
        *,
        subject_id: str,
        side_work_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        # The subject row is already locked before this lookup. Every Runtime
        # mutation of this chain must pass the same fenced subject lock, while
        # Admin deliberately has DELETE rather than broad UPDATE on these rows.
        suffix = ""
        row = connection.execute(
            "SELECT interaction.interaction_id, evidence.evidence_id, "
            "opportunity.opportunity_id, evidence.artifact_id, artifact.content_digest, "
            "opportunity.current_disposition, interaction.subject_id "
            "FROM armi.party_input_interactions AS interaction "
            "JOIN armi.external_evidence AS evidence "
            "ON evidence.interaction_id = interaction.interaction_id "
            "AND evidence.source_kind = 'creator_input' "
            "JOIN armi.opportunities AS opportunity ON opportunity.evidence_id = evidence.evidence_id "
            "JOIN armi.artifacts AS artifact ON artifact.artifact_id = evidence.artifact_id "
            "WHERE interaction.interaction_id = %s" + suffix,
            (spec["interaction_id"],),
        ).fetchone()
        if row is None or str(row[6]) != subject_id:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-NOT-FOUND")
        blocked = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM armi.cognitive_episodes WHERE opportunity_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.web_research_intents WHERE source_opportunity_id = %s)",
            (row[2], row[2]),
        ).fetchone()
        if row[5] != "open" or (blocked is not None and bool(blocked[0])):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-COMMITTED")
        shared = self._artifact_has_other_references(
            connection, str(row[3]), excluded_evidence_id=str(row[1])
        )
        audit_count_row = connection.execute(
            "SELECT count(*) FROM armi.audit_events "
            "WHERE target_ref = ANY(%s::uuid[]) OR request_ref = ANY(%s::uuid[])",
            (
                [str(row[0]), str(row[1]), str(row[2])],
                [str(row[0]), str(row[1]), str(row[2])],
            ),
        ).fetchone()
        audit_count = 0 if audit_count_row is None else int(audit_count_row[0])
        before = _digest(
            {
                "interaction_id": str(row[0]),
                "evidence_id": str(row[1]),
                "opportunity_id": str(row[2]),
                "artifact_id": str(row[3]),
                "artifact_shared": shared,
            }
        )
        after = _digest(
            {
                "interaction_absent": True,
                "evidence_absent": True,
                "opportunity_absent": True,
                "artifact_id": str(row[3]),
                "artifact_retained": shared,
                "side_work_id": None if shared else side_work_id,
            }
        )
        return {
            "target_identity": _digest({"interaction_id": str(row[0])}),
            "target_versions": {"input_chain": 1},
            "target_count": 4 + audit_count,
            "dependency_count": 3,
            "side_work_required": not shared,
            "before_digest": before,
            "after_digest": after,
            "handler": {
                "interaction_id": str(row[0]),
                "evidence_id": str(row[1]),
                "opportunity_id": str(row[2]),
                "artifact_id": str(row[3]),
                "content_digest": str(row[4]),
                "artifact_shared": shared,
                "audit_count": audit_count,
                "side_work_id": side_work_id,
            },
            "status_spec": {
                "interaction_id": str(row[0]),
                "evidence_id": str(row[1]),
                "opportunity_id": str(row[2]),
                "artifact_id": str(row[3]),
                "artifact_shared": shared,
            },
        }

    @staticmethod
    def _work_snapshot(
        connection: psycopg.Connection[Any],
        spec: dict[str, Any],
        *,
        for_update: bool,
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE OF work" if for_update else ""
        row = connection.execute(
            "SELECT work.work_id, work.status, work.lease_token, work.attempt_count, "
            "work.max_attempts, work.deadline_at, work.lease_expires_at, "
            "instance.status, work.owner_ref "
            "FROM armi.durable_work AS work "
            "LEFT JOIN armi.runtime_instances AS instance "
            "ON instance.runtime_instance_id = work.lease_owner "
            "WHERE work.work_id = %s" + suffix,
            (spec["work_id"],),
        ).fetchone()
        if row is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-FOUND")
        eligible = connection.execute(
            "SELECT %s = 'leased' AND %s <= statement_timestamp() "
            "AND %s > statement_timestamp() AND %s < %s",
            (row[1], row[6], row[5], row[3], row[4]),
        ).fetchone()
        if (
            eligible is None
            or not bool(eligible[0])
            or row[7] not in {"stopped", "fenced"}
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-NOT-STUCK")
        before = _digest(
            {"work_id": str(row[0]), "status": str(row[1]), "lease_token": int(row[2])}
        )
        after = _digest(
            {"work_id": str(row[0]), "status": "ready", "lease_token": int(row[2]) + 1}
        )
        return {
            "target_identity": _digest({"work_id": str(row[0])}),
            "target_versions": {"lease_token": int(row[2])},
            "target_count": 1,
            "dependency_count": 1,
            "side_work_required": False,
            "before_digest": before,
            "after_digest": after,
            "handler": {"work_id": str(row[0]), "lease_token": int(row[2])},
            "status_spec": {"work_id": str(row[0])},
        }

    @staticmethod
    def _effect_snapshot(
        connection: psycopg.Connection[Any],
        spec: dict[str, Any],
        *,
        result_id: str,
        for_update: bool,
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE OF effect, operation, outbox" if for_update else ""
        row = connection.execute(
            "SELECT effect.effect_id, effect.status, effect.current_attempt_id, "
            "effect.payload_digest, effect.operation_id, "
            "CASE WHEN operation.phase = 'terminal' THEN operation.outcome "
            "ELSE operation.phase END, outbox.effect_outbox_item_id, "
            "delivery.delivery_id, delivery.receipt_digest "
            "FROM armi.effects AS effect "
            "JOIN armi.action_operations AS operation "
            "ON operation.operation_id = effect.operation_id "
            "JOIN armi.effect_outbox_items AS outbox ON outbox.effect_id = effect.effect_id "
            "LEFT JOIN armi.local_inbox_deliveries AS delivery "
            "ON delivery.effect_id = effect.effect_id "
            "AND delivery.payload_digest = effect.payload_digest "
            "WHERE effect.effect_id = %s" + suffix,
            (spec["effect_id"],),
        ).fetchone()
        if row is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-NOT-FOUND")
        if row[1] != "unknown" or row[2] is None:
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-NOT-UNKNOWN")
        completed = row[7] is not None
        result_status = "completed" if completed else "failed"
        observation_digest = _digest(
            {
                "effect_id": str(row[0]),
                "delivery_id": None if row[7] is None else str(row[7]),
                "receipt_digest": None if row[8] is None else str(row[8]),
                "result": result_status,
            }
        )
        before = _digest(
            {
                "effect_id": str(row[0]),
                "status": str(row[1]),
                "attempt_id": str(row[2]),
            }
        )
        after = _digest(
            {
                "effect_id": str(row[0]),
                "status": result_status,
                "observation_id": result_id,
                "observation_digest": observation_digest,
            }
        )
        return {
            "target_identity": _digest({"effect_id": str(row[0])}),
            "target_versions": {"effect_state": "unknown"},
            "target_count": 3,
            "dependency_count": 2,
            "side_work_required": False,
            "before_digest": before,
            "after_digest": after,
            "handler": {
                "effect_id": str(row[0]),
                "attempt_id": str(row[2]),
                "operation_id": str(row[4]),
                "outbox_id": str(row[6]),
                "delivery_id": None if row[7] is None else str(row[7]),
                "observation_id": result_id,
                "observation_digest": observation_digest,
                "result_status": result_status,
            },
            "status_spec": {"effect_id": str(row[0])},
        }

    def _apply_handler(
        self,
        connection: psycopg.Connection[Any],
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
            changed = connection.execute(
                "UPDATE armi.durable_work SET status = 'ready', "
                "not_before = statement_timestamp(), current_attempt_id = NULL, "
                "lease_owner = NULL, lease_expires_at = NULL, lease_token = lease_token + 1, "
                "last_error_code = NULL, updated_at = statement_timestamp() "
                "WHERE work_id = %s AND status = 'leased' AND lease_token = %s",
                (handler["work_id"], handler["lease_token"]),
            ).rowcount
            if changed != 1:
                raise AdminCorrectionGatewayError("ADMIN-CORRECTION-WORK-CAS")
        elif kind == "reconcile_unknown_creator_effect":
            self._reconcile_effect(connection, handler)
        return {
            "side_work_id": handler.get("side_work_id")
            if snapshot["side_work_required"]
            else None
        }

    @staticmethod
    def _delete_input(
        connection: psycopg.Connection[Any],
        snapshot: dict[str, Any],
        handler: dict[str, Any],
    ) -> None:
        ids = [
            handler["interaction_id"],
            handler["evidence_id"],
            handler["opportunity_id"],
        ]
        connection.execute(
            "DELETE FROM armi.audit_events "
            "WHERE target_ref = ANY(%s::uuid[]) OR request_ref = ANY(%s::uuid[])",
            (ids, ids),
        )
        connection.execute(
            "DELETE FROM armi.scene_timeline_items "
            "WHERE source_kind = 'creator_input' AND source_ref = %s",
            (handler["interaction_id"],),
        )
        if (
            connection.execute(
                "DELETE FROM armi.opportunities WHERE opportunity_id = %s "
                "AND current_disposition = 'open'",
                (handler["opportunity_id"],),
            ).rowcount
            != 1
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-INPUT-CAS")
        connection.execute(
            "DELETE FROM armi.external_evidence WHERE evidence_id = %s",
            (handler["evidence_id"],),
        )
        connection.execute(
            "DELETE FROM armi.party_input_interactions WHERE interaction_id = %s",
            (handler["interaction_id"],),
        )
        if not handler["artifact_shared"]:
            deleted = connection.execute(
                "DELETE FROM armi.artifacts WHERE artifact_id = %s",
                (handler["artifact_id"],),
            ).rowcount
            if deleted != 1:
                raise AdminCorrectionGatewayError(
                    "ADMIN-CORRECTION-ARTIFACT-REFERENCED"
                )
            work_id = handler["side_work_id"]
            trace_id = UUID(str(work_id)).hex
            connection.execute(
                "INSERT INTO armi.durable_work (work_id, work_kind, owner_kind, owner_ref, "
                "subject_id, idempotency_key, payload_kind, payload_ref, payload_digest, "
                "priority, not_before, deadline_at, status, max_attempts, attempt_count, "
                "lease_token, trace_id) VALUES ("
                "%s, 'admin.correction.artifact-cleanup', 'admin_correction', %s, %s, %s, "
                "'artifact', %s, %s, 100, statement_timestamp(), "
                "statement_timestamp() + interval '24 hours', 'ready', 1, 0, 0, %s)",
                (
                    work_id,
                    snapshot["result_id"],
                    snapshot["subject_id"],
                    str(snapshot["result_id"]),
                    handler["artifact_id"],
                    handler["content_digest"],
                    trace_id,
                ),
            )

    @staticmethod
    def _reconcile_effect(
        connection: psycopg.Connection[Any], handler: dict[str, Any]
    ) -> None:
        completed = handler["result_status"] == "completed"
        connection.execute(
            "INSERT INTO armi.effect_observations (effect_observation_id, effect_id, "
            "effect_attempt_id, observation_kind, reliability, receiver_ref, "
            "observation_digest) VALUES (%s, %s, %s, 'query', "
            "'reliable', NULL, %s)",
            (
                handler["observation_id"],
                handler["effect_id"],
                handler["attempt_id"],
                handler["observation_digest"],
            ),
        )
        if (
            connection.execute(
                "UPDATE armi.effects SET status = %s, verification_status = 'verified', "
                "current_observation_id = %s, "
                "settled_at = statement_timestamp() WHERE effect_id = %s AND status = 'unknown'",
                (
                    "completed" if completed else "failed",
                    handler["observation_id"],
                    handler["effect_id"],
                ),
            ).rowcount
            != 1
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-CAS")
        if (
            connection.execute(
                "UPDATE armi.effect_outbox_items SET status = %s, claim_owner = NULL, "
                "claim_expires_at = NULL, "
                "delivered_at = CASE WHEN %s THEN statement_timestamp() ELSE NULL END, "
                "last_error_code = %s "
                "WHERE effect_outbox_item_id = %s",
                (
                    "delivered" if completed else "dead",
                    completed,
                    None if completed else "EFFECT-DELIVERY-NOT-FOUND",
                    handler["outbox_id"],
                ),
            ).rowcount
            != 1
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-OUTBOX")
        if (
            connection.execute(
                "UPDATE armi.action_operations SET current_status = %s, "
                "reason_code = %s, completed_at = statement_timestamp() "
                "WHERE operation_id = %s",
                (
                    "effect_completed" if completed else "effect_failed",
                    None if completed else "EFFECT-DELIVERY-NOT-FOUND",
                    handler["operation_id"],
                ),
            ).rowcount
            != 1
        ):
            raise AdminCorrectionGatewayError("ADMIN-CORRECTION-EFFECT-OPERATION")

    def _current_target_digest(
        self,
        connection: psycopg.Connection[Any],
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
            row = connection.execute(
                "SELECT evidence.evidence_id, opportunity.opportunity_id, evidence.artifact_id "
                "FROM armi.party_input_interactions AS interaction "
                "LEFT JOIN armi.external_evidence AS evidence "
                "ON evidence.interaction_id = interaction.interaction_id "
                "LEFT JOIN armi.opportunities AS opportunity ON opportunity.evidence_id = evidence.evidence_id "
                "WHERE interaction.interaction_id = %s",
                (status_spec["interaction_id"],),
            ).fetchone()
            if row is None:
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
                    "evidence_id": None if row[0] is None else str(row[0]),
                    "opportunity_id": None if row[1] is None else str(row[1]),
                    "artifact_id": None if row[2] is None else str(row[2]),
                    "artifact_shared": bool(status_spec["artifact_shared"]),
                }
            )
        if kind == "requeue_stuck_work":
            row = connection.execute(
                "SELECT status, lease_token FROM armi.durable_work WHERE work_id = %s",
                (status_spec["work_id"],),
            ).fetchone()
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
        row = connection.execute(
            "SELECT status, current_observation_id FROM armi.effects WHERE effect_id = %s",
            (status_spec["effect_id"],),
        ).fetchone()
        if row is None:
            return _digest({"missing": True})
        observation = (
            connection.execute(
                "SELECT observation_digest FROM armi.effect_observations "
                "WHERE effect_observation_id = %s",
                (row[1],),
            ).fetchone()
            if row[1] is not None
            else None
        )
        return _digest(
            {
                "effect_id": status_spec["effect_id"],
                "status": str(row[0]),
                "observation_id": None if row[1] is None else str(row[1]),
                "observation_digest": None
                if observation is None
                else str(observation[0]),
            }
        )

    @staticmethod
    def _existing_side_work(
        connection: psycopg.Connection[Any], side_work_id: str
    ) -> str | None:
        row = connection.execute(
            "SELECT work_id FROM armi.durable_work WHERE work_id = %s "
            "AND work_kind = 'admin.correction.artifact-cleanup'",
            (side_work_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _artifact_has_other_references(
        connection: psycopg.Connection[Any],
        artifact_id: str,
        *,
        excluded_evidence_id: str,
    ) -> bool:
        row = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM armi.prompt_revisions WHERE content_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.external_evidence WHERE artifact_id = %s AND evidence_id <> %s) "
            "OR EXISTS (SELECT 1 FROM armi.cognitive_episodes WHERE context_manifest_artifact_id = %s OR compiled_context_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.cognitive_attempts WHERE request_artifact_id = %s OR response_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.cognitive_candidate_validations WHERE change_set_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.action_intent_revisions WHERE response_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.effects WHERE payload_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.local_inbox_deliveries WHERE payload_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.web_observation_requests WHERE request_artifact_id = %s OR result_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.observation_attempts WHERE result_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.web_research_intents WHERE query_artifact_id = %s) "
            "OR EXISTS (SELECT 1 FROM armi.web_evidence_sources WHERE source_artifact_id = %s)",
            (
                artifact_id,
                artifact_id,
                excluded_evidence_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
                artifact_id,
            ),
        ).fetchone()
        return row is not None and bool(row[0])

    def _pool(self) -> AdminRoleBoundPool:
        return AdminRoleBoundPool(self._conninfo, expected_role=self._expected_role)


__all__ = ("AdminCorrectionGateway", "AdminCorrectionGatewayError")
