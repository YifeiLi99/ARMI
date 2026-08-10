"""PostgreSQL owner for T-05 policy and effect registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    EffectId,
    EffectObservationKind,
    EffectObservationReliability,
    EffectRegistrationResult,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    PolicyDecisionId,
    WorkLease,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId
from psycopg import sql

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class EffectRegistrationSnapshot:
    operation_id: UUID
    root_operation_id: UUID
    action_revision_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    trace_id: TraceId
    effect_kind: str
    capability_kind: str
    operation_class: str
    purpose: str
    action_intent_id: UUID


class PostgreSQLEffectLedgerRepository:
    __slots__ = ()

    async def snapshot(
        self, uow: PostgreSQLUnitOfWork, lease: WorkLease
    ) -> EffectRegistrationSnapshot:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
            SELECT operation.operation_id, operation.root_opportunity_id,
                   revision.action_intent_revision_id, operation.subject_id,
                   operation.scene_id, operation.context_party_id,
                   COALESCE(revision.response_artifact_id, source.task_manifest_artifact_id),
                   COALESCE(revision.response_digest, revision.task_manifest_digest),
                   artifact.byte_size, work.trace_id,
                   operation.operation_kind, revision.capability_kind,
                   revision.operation_class, revision.purpose,
                   operation.action_intent_id
            FROM armi.durable_work AS work
            JOIN armi.action_operations AS operation
              ON operation.registration_work_id = work.work_id
             AND operation.phase = 'admitted' AND operation.outcome IS NULL
            JOIN armi.action_intents AS intent ON intent.action_intent_id = operation.action_intent_id
            JOIN armi.action_intent_revisions AS revision
              ON revision.action_intent_revision_id = intent.current_revision_id
            LEFT JOIN armi.codex_task_sources AS source
              ON source.codex_task_source_id = revision.codex_task_source_id
            JOIN armi.artifacts AS artifact
              ON artifact.artifact_id = COALESCE(
                    revision.response_artifact_id, source.task_manifest_artifact_id
                 )
            WHERE work.work_id = %s AND work.work_kind = 'effect.register'
              AND work.status = 'leased' AND work.current_attempt_id = %s
              AND work.lease_owner = %s AND work.lease_token = %s
              AND work.lease_expires_at > statement_timestamp()
            """,
                (lease.work_id.value, lease.attempt_id.value, lease.owner, lease.token),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-WORK-STALE")
        return EffectRegistrationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            Digest(str(row[7])),
            int(row[8]),
            TraceId(str(row[9])),
            "codex_delegation"
            if str(row[10]) == "codex_delegation"
            else "creator_response",
            str(row[11]),
            str(row[12]),
            str(row[13]),
            row[14],
        )

    async def settle(
        self,
        uow: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: EffectRegistrationSnapshot,
        integrity_ok: bool,
    ) -> EffectRegistrationResult | None:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        if uow.runtime_fence is None:
            raise EffectViolation("EFFECT-FENCE")
        locked = await (
            await connection.execute(
                "SELECT phase, outcome FROM armi.action_operations WHERE operation_id = %s FOR UPDATE",
                (snapshot.operation_id,),
            )
        ).fetchone()
        if locked is None or locked != ("admitted", None):
            raise EffectViolation("EFFECT-WORK-STALE")
        registration_digest = _registration_digest(snapshot)
        existing = await self._existing(connection, snapshot, registration_digest)
        if existing is not None:
            await uow.work.complete(
                lease, WorkResultRef("effect", existing.effect_id.value)
            )
            return existing

        outcome = "denied"
        reason = "POLICY-GRANT-NOT-CURRENT"
        grant_id: UUID | None = None
        valid_until = None
        if not integrity_ok:
            outcome, reason = "unavailable", "POLICY-PAYLOAD-UNAVAILABLE"
        else:
            capability = await (
                await connection.execute(
                    """
                    SELECT capability_id, availability_status
                    FROM armi.capabilities
                    WHERE capability_kind = %s AND operation_class = %s
                    """,
                    (snapshot.capability_kind, snapshot.operation_class),
                )
            ).fetchone()
            if capability is None or str(capability[1]) != "available":
                outcome, reason = "unavailable", "POLICY-CAPABILITY-UNAVAILABLE"
            else:
                grant = await (
                    await connection.execute(
                        """
                    SELECT grant_id, valid_until FROM armi.permission_grants
                    WHERE capability_id = %s
                      AND subject_id = %s AND interaction_scene_id = %s AND creator_party_id = %s
                      AND operation_class = %s AND purpose = %s
                      AND status = 'active' AND valid_from <= statement_timestamp()
                      AND statement_timestamp() < valid_until AND consumed_uses < max_uses
                      AND (
                        (%s = 'creator_response' AND audience_scope = 'creator'
                          AND data_scope = 'creator_visible_response'
                          AND %s <= max_payload_bytes)
                        OR (%s = 'codex_delegation' AND workspace_scope = 'isolated_ephemeral'
                          AND artifact_scope = 'explicit_only' AND network_access = false
                          AND max_uses = 1)
                      )
                    ORDER BY valid_until, grant_id LIMIT 1 FOR UPDATE
                    """,
                        (
                            capability[0],
                            snapshot.subject_id,
                            snapshot.scene_id,
                            snapshot.creator_party_id,
                            snapshot.operation_class,
                            snapshot.purpose,
                            snapshot.effect_kind,
                            snapshot.payload_bytes,
                            snapshot.effect_kind,
                        ),
                    )
                ).fetchone()
                if grant is not None:
                    grant_id, valid_until = grant[0], grant[1]
                    consumed = await (
                        await connection.execute(
                            """
                        UPDATE armi.permission_grants SET consumed_uses = consumed_uses + 1
                        WHERE grant_id = %s AND status = 'active'
                          AND statement_timestamp() < valid_until AND consumed_uses < max_uses
                        RETURNING consumed_uses
                        """,
                            (grant_id,),
                        )
                    ).fetchone()
                    if consumed is not None:
                        outcome, reason = "allowed", "POLICY-GRANT-ALLOWED"
                    else:
                        grant_id, valid_until = None, None

        decision_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.policy_decisions (
                policy_decision_id, action_intent_revision_id, operation_id,
                matched_grant_id, decision_outcome, policy_identity,
                reason_code, valid_until) VALUES (%s, %s, %s, %s, %s, 'armi.policy-engine.deterministic-v1', %s, %s)
            """,
            (
                decision_id,
                snapshot.action_revision_id,
                snapshot.operation_id,
                grant_id,
                outcome,
                reason,
                valid_until,
            ),
        )
        result: EffectRegistrationResult | None = None
        if outcome == "allowed":
            effect_id, outbox_id = uuid7(), uuid7()
            row = await (
                await connection.execute(
                    """
                INSERT INTO armi.effects (
                    effect_id, action_intent_revision_id, action_intent_id, operation_id,
                    policy_decision_id, subject_id, scene_id, context_party_id,
                    payload_artifact_id, payload_digest, payload_bytes, effect_kind,
                    capability_kind, operation_class, audience_scope, data_scope, purpose,
                    authorization_basis, destination_kind, destination_party_id,
                    registration_digest, trace_id, status, verification_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,'creator_grant',%s,%s,%s,%s,
                    'registered','not_started')
                RETURNING registered_at
                """,
                    (
                        effect_id,
                        snapshot.action_revision_id,
                        snapshot.action_intent_id,
                        snapshot.operation_id,
                        decision_id,
                        snapshot.subject_id,
                        snapshot.scene_id,
                        snapshot.creator_party_id,
                        snapshot.artifact_id,
                        snapshot.payload_digest.value,
                        snapshot.payload_bytes,
                        snapshot.effect_kind,
                        snapshot.capability_kind,
                        snapshot.operation_class,
                        "creator"
                        if snapshot.effect_kind == "creator_response"
                        else None,
                        "creator_visible_response"
                        if snapshot.effect_kind == "creator_response"
                        else None,
                        snapshot.purpose,
                        "creator_inbox"
                        if snapshot.effect_kind == "creator_response"
                        else "codex_workspace",
                        snapshot.creator_party_id,
                        registration_digest.value,
                        snapshot.trace_id.value,
                    ),
                )
            ).fetchone()
            row = cast(tuple[Any, ...], row)
            if snapshot.effect_kind == "creator_response":
                await connection.execute(
                    """UPDATE armi.dialogue_decisions
                       SET effect_id = %s
                       WHERE action_intent_id = %s
                         AND decision_kind = 'reply' AND effect_id IS NULL""",
                    (effect_id, snapshot.action_intent_id),
                )
            await connection.execute(
                """
                INSERT INTO armi.effect_outbox_items (
                    effect_outbox_item_id, effect_id, message_kind,
                    status, dispatch_deadline, max_attempts) VALUES (%s, %s, 'effect.dispatch', 'ready', %s, %s)
                """,
                (
                    outbox_id,
                    effect_id,
                    valid_until,
                    1 if snapshot.effect_kind == "codex_delegation" else 2,
                ),
            )
            await connection.execute(
                """
                UPDATE armi.action_operations SET phase='effect_registered', outcome=NULL,
                    current_policy_decision_id=%s, effect_id=%s,
                    effect_registered_at=%s
                WHERE operation_id=%s AND phase='admitted' AND outcome IS NULL
                """,
                (
                    decision_id,
                    effect_id,
                    row[0],
                    snapshot.operation_id,
                ),
            )
            await uow.work.complete(lease, WorkResultRef("effect", effect_id))
            result = EffectRegistrationResult(
                EffectId(effect_id),
                PolicyDecisionId(decision_id),
                EffectStatus.REGISTERED,
                EffectVerificationStatus.NOT_STARTED,
                registration_digest,
                Instant(row[0]),
            )
        else:
            await connection.execute(
                "UPDATE armi.action_operations SET phase='terminal', outcome=%s, current_policy_decision_id=%s, reason_code=%s, completed_at=statement_timestamp() WHERE operation_id=%s AND phase='admitted' AND outcome IS NULL",
                (
                    "denied" if outcome == "denied" else "failed",
                    decision_id,
                    reason,
                    snapshot.operation_id,
                ),
            )
            await uow.work.complete(
                lease,
                WorkResultRef("creator_response_operation", snapshot.operation_id),
            )
        await uow.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", uow.environment_id),
                Purpose("effect.registration"),
                "effect.registration.settled",
                AuditReference("creator_response_operation", snapshot.operation_id),
                AuditResultStatus.ACCEPTED
                if outcome == "allowed"
                else (
                    AuditResultStatus.REJECTED
                    if outcome == "denied"
                    else AuditResultStatus.UNAVAILABLE
                ),
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                grant=AuditReference("permission_grant", grant_id)
                if grant_id is not None
                else None,
            )
        )
        return result

    async def get_effect(
        self, uow: PostgreSQLUnitOfWork, effect_id: EffectId, creator_party_id: UUID
    ) -> EffectView:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
            SELECT effect.effect_id, operation.root_opportunity_id, effect.effect_kind,
                   request.capability_request_id, permission.grant_id,
                   effect.capability_kind, effect.status,
                   effect.verification_status, effect.registered_at, effect.cancelled_at,
                   (SELECT count(*) FROM armi.effect_attempts AS attempt
                    WHERE attempt.effect_id = effect.effect_id),
                   observation.observation_kind, observation.reliability,
                   effect.settled_at,
                   verification.execution_status, verification.cleanup_status,
                   verification.source_tree_digest, verification.final_tree_digest,
                   verification.patch_digest, verification.changed_path_count,
                   result_opportunity.current_disposition
            FROM armi.effects AS effect
            JOIN armi.action_operations AS operation
              ON operation.operation_id = effect.operation_id
            JOIN armi.policy_decisions AS policy
              ON policy.policy_decision_id = effect.policy_decision_id
            JOIN armi.permission_grants AS permission
              ON permission.grant_id = policy.matched_grant_id
             AND permission.creator_party_id = effect.context_party_id
            JOIN armi.capability_requests AS request
              ON request.capability_request_id = permission.capability_request_id
             AND request.capability_kind = effect.capability_kind
            LEFT JOIN armi.effect_observations AS observation
              ON observation.effect_observation_id = effect.current_observation_id
            LEFT JOIN armi.codex_verification_results AS verification
              ON verification.effect_id = effect.effect_id
            LEFT JOIN armi.codex_result_sources AS result_source
              ON result_source.codex_verification_id = verification.codex_verification_id
            LEFT JOIN armi.opportunities AS result_opportunity
              ON result_opportunity.opportunity_id = result_source.opportunity_id
            WHERE effect.effect_id=%s AND effect.context_party_id=%s
            """,
                (effect_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        raw_effect_kind = str(row[2])
        if raw_effect_kind not in {"creator_response", "codex_delegation"}:
            raise EffectViolation("CON-EFFECT-KIND")
        effect_kind = cast(
            Literal["creator_response", "codex_delegation"], raw_effect_kind
        )
        execution_status = None if row[14] is None else str(row[14])
        return EffectView(
            effect_id=EffectId(row[0]),
            root_operation_ref=row[1],
            effect_kind=effect_kind,
            status=EffectStatus(str(row[6])),
            verification_status=EffectVerificationStatus(str(row[7])),
            registered_at=Instant(row[8]),
            capability_request_ref=row[3],
            grant_ref=row[4],
            capability_kind=cast(
                Literal["creator.scene.reply", "codex.delegated-work"], str(row[5])
            ),
            cancelled_at=Instant(row[9]) if row[9] is not None else None,
            attempt_count=int(row[10]),
            last_observation_kind=(
                EffectObservationKind(str(row[11])) if row[11] is not None else None
            ),
            last_observation_reliability=(
                EffectObservationReliability(str(row[12]))
                if row[12] is not None
                else None
            ),
            verification_action=(
                (
                    "verify_codex_result"
                    if effect_kind == "codex_delegation"
                    else "verify_creator_inbox"
                )
                if str(row[6]) == "unknown"
                else None
            ),
            settled_at=Instant(row[13]) if row[13] is not None else None,
            # The current schema does not persist the selected execution profile.
            # Do not guess a model identity in a public projection.
            model_id=None,
            sdk_identity="openai-codex==0.144.4"
            if execution_status is not None
            else None,
            source_tree_digest=Digest(str(row[16])) if row[16] is not None else None,
            result_tree_digest=Digest(str(row[17])) if row[17] is not None else None,
            patch_digest=Digest(str(row[18])) if row[18] is not None else None,
            changed_path_count=int(row[19]) if row[19] is not None else None,
            validation_status=(
                "passed"
                if execution_status == "verified"
                else (
                    "not_run"
                    if execution_status in {"unknown", "cancelled"}
                    else "failed"
                )
            )
            if execution_status is not None
            else None,
            cleanup_status=("succeeded" if str(row[15]) == "clean" else "failed")
            if row[15] is not None
            else None,
            result_acceptance_status=(
                "accepted" if str(row[20]) == "resolved" else "pending"
            )
            if row[20] is not None
            else None,
        )

    async def payload_reference(
        self, uow: PostgreSQLUnitOfWork, effect_id: EffectId
    ) -> tuple[UUID, Digest, int]:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                "SELECT payload_artifact_id, payload_digest, payload_bytes FROM armi.effects WHERE effect_id=%s AND status='completed'",
                (effect_id.value,),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return row[0], Digest(str(row[1])), int(row[2])

    async def codex_manifest_reference(
        self,
        uow: PostgreSQLUnitOfWork,
        effect_id: EffectId,
    ) -> tuple[UUID, Digest, int]:
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT artifact.artifact_id, artifact.content_digest,
                       artifact.byte_size
                FROM armi.effects AS effect
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id
                   = effect.action_intent_revision_id
                JOIN armi.codex_task_sources AS source
                  ON source.codex_task_source_id = revision.codex_task_source_id
                JOIN armi.artifacts AS artifact
                  ON artifact.artifact_id = source.task_manifest_artifact_id
                WHERE effect.effect_id=%s
                  AND effect.effect_kind='codex_delegation'
                """,
                (effect_id.value,),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return row[0], Digest(str(row[1])), int(row[2])

    async def codex_artifact_reference(
        self,
        uow: PostgreSQLUnitOfWork,
        effect_id: EffectId,
        creator_party_id: UUID,
        kind: str,
    ) -> tuple[UUID, Digest, int, str]:
        column = {
            "patch": "patch_artifact_id",
            "final_result": "final_result_artifact_id",
            "validation_report": "validation_report_artifact_id",
        }.get(kind)
        if column is None:
            raise EffectViolation("EFFECT-ARTIFACT-KIND")
        connection = uow._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                sql.SQL(
                    """
                SELECT artifact.artifact_id, artifact.content_digest,
                       artifact.byte_size, artifact.media_type
                FROM armi.effects AS effect
                JOIN armi.codex_verification_results AS verification
                  ON verification.effect_id = effect.effect_id
                JOIN armi.artifacts AS artifact
                  ON artifact.artifact_id = verification.{column}
                WHERE effect.effect_id=%s
                  AND effect.context_party_id=%s
                  AND effect.effect_kind='codex_delegation'
                  AND effect.status='completed'
                  AND effect.verification_status='verified'
                """
                ).format(column=sql.Identifier(column)),
                (effect_id.value, creator_party_id),
            )
        ).fetchone()
        if row is None:
            raise EffectViolation("SCOPE-EFFECT-NOT-VISIBLE")
        return row[0], Digest(str(row[1])), int(row[2]), str(row[3])

    async def _existing(
        self,
        connection: Any,
        snapshot: EffectRegistrationSnapshot,
        registration_digest: Digest,
    ) -> EffectRegistrationResult | None:
        row = await (
            await connection.execute(
                """
            SELECT effect.effect_id, effect.policy_decision_id, effect.status,
                   effect.verification_status, effect.registration_digest, effect.registered_at
            FROM armi.effects AS effect
            WHERE effect.action_intent_revision_id=%s AND effect.effect_kind=%s
            """,
                (snapshot.action_revision_id, snapshot.effect_kind),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[4]) != registration_digest.value:
            raise EffectViolation("EFFECT-IDEMPOTENCY-CONFLICT")
        return EffectRegistrationResult(
            EffectId(row[0]),
            PolicyDecisionId(row[1]),
            EffectStatus(str(row[2])),
            EffectVerificationStatus(str(row[3])),
            Digest(str(row[4])),
            Instant(row[5]),
        )


def _registration_digest(snapshot: EffectRegistrationSnapshot) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.effect-registration.v1",
                    "action_intent_revision_id": str(snapshot.action_revision_id),
                    "effect_kind": snapshot.effect_kind,
                    "subject_id": str(snapshot.subject_id),
                    "scene_id": str(snapshot.scene_id),
                    "creator_party_id": str(snapshot.creator_party_id),
                    "payload_digest": snapshot.payload_digest.value,
                    "payload_bytes": snapshot.payload_bytes,
                    "purpose": snapshot.purpose,
                },
            )
        )
    )


__all__ = ("EffectRegistrationSnapshot", "PostgreSQLEffectLedgerRepository")
