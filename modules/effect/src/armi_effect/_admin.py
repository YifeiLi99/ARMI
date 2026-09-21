from typing import cast
from uuid import UUID

from armi_kernel.contracts import Instant
from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import EffectAdminSnapshot


class PostgreSQLEffectAdmin:
    __slots__ = ()

    def content_busy(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS(SELECT 1 FROM armi.effects WHERE subject_id=%s AND status IN ('registered','dispatching'))",
            (subject_id,),
        ).fetchone()
        return row is not None and bool(row[0])

    def for_intent(
        self, transaction: PostgreSQLAdminTransaction, *, action_intent_id: UUID
    ) -> tuple[EffectAdminSnapshot, ...]:
        rows = transaction.execute(
            "SELECT effect_id FROM armi.effects WHERE action_intent_id=%s ORDER BY effect_id LIMIT 32",
            (action_intent_id,),
        ).fetchall()
        return tuple(
            item
            for row in rows
            if (item := self.snapshot(transaction, effect_id=cast(UUID, row[0])))
            is not None
        )

    def snapshot(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        effect_id: UUID,
        for_update: bool = False,
    ) -> EffectAdminSnapshot | None:
        suffix = " FOR UPDATE OF effect" if for_update else ""
        row = transaction.execute(
            "SELECT effect.effect_id,effect.status,effect.current_attempt_id,effect.payload_digest,"
            "effect.action_intent_id,effect.local_delivery_id,effect.local_receipt_digest "
            "FROM armi.effects AS effect "
            "WHERE effect.effect_id=%s" + suffix,
            (effect_id,),
        ).fetchone()
        return (
            None
            if row is None
            else EffectAdminSnapshot(
                cast(UUID, row[0]),
                str(row[1]),
                cast(UUID | None, row[2]),
                str(row[3]),
                cast(UUID | None, row[4]),
                cast(UUID | None, row[5]),
                None if row[6] is None else str(row[6]),
            )
        )

    def reconcile(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        snapshot: EffectAdminSnapshot,
        observation_id: UUID,
        observation_digest: str,
        conclusion: str,
        reliability: str,
        reason_code: str,
        evidence_kind: str,
        evidence_ref: str | None,
        evidence_digest: str | None,
        source_identity: str,
        observed_at: Instant,
    ) -> bool:
        transaction.execute(
            "INSERT INTO armi.effect_observations "
            "(effect_observation_id,effect_id,effect_attempt_id,observation_kind,"
            "reliability,receiver_ref,observation_digest,conclusion,reason_code,"
            "evidence_kind,evidence_ref,evidence_digest,source_identity,observed_at) "
            "VALUES (%s,%s,%s,'query',%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                observation_id,
                snapshot.effect_id,
                snapshot.attempt_id,
                reliability,
                observation_digest,
                conclusion,
                reason_code,
                evidence_kind,
                evidence_ref,
                evidence_digest,
                source_identity,
                observed_at.value,
            ),
        )
        verification = (
            "inconclusive"
            if conclusion == "unknown"
            else "operator_attested"
            if reliability == "operator_attested"
            else "verified"
        )
        changed = transaction.execute(
            "UPDATE armi.effects SET status=%s,verification_status=%s,"
            "current_observation_id=%s,settled_at=%s WHERE effect_id=%s AND status='unknown'",
            (
                conclusion,
                verification,
                observation_id,
                observed_at.value,
                snapshot.effect_id,
            ),
        ).rowcount
        if conclusion == "unknown":
            return changed == 1
        dispatch = transaction.execute(
            "UPDATE armi.effects SET dispatch_status=%s,claim_owner=NULL,claim_expires_at=NULL,delivered_at=CASE WHEN %s THEN statement_timestamp() ELSE NULL END,last_error_code=%s WHERE effect_id=%s",
            (
                "delivered" if conclusion == "completed" else "dead",
                conclusion == "completed",
                None if conclusion == "completed" else reason_code,
                snapshot.effect_id,
            ),
        ).rowcount
        return changed == 1 and dispatch == 1

    def current_state(
        self, transaction: PostgreSQLAdminTransaction, *, effect_id: UUID
    ) -> tuple[str, UUID | None, str | None] | None:
        row = transaction.execute(
            "SELECT effect.status,effect.current_observation_id,observation.observation_digest FROM armi.effects AS effect LEFT JOIN armi.effect_observations AS observation ON observation.effect_observation_id=effect.current_observation_id WHERE effect.effect_id=%s",
            (effect_id,),
        ).fetchone()
        return (
            None
            if row is None
            else (
                str(row[0]),
                cast(UUID | None, row[1]),
                None if row[2] is None else str(row[2]),
            )
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT effect_id FROM armi.effects WHERE effect_id=ANY(%s::uuid[]) ORDER BY effect_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        row = transaction.execute(
            "SELECT count(*) FROM armi.effects WHERE payload_artifact_id=%s",
            (artifact_id,),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLEffectAdmin",)
