from typing import cast
from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import EffectAdminSnapshot


class PostgreSQLEffectAdmin:
    __slots__ = ()

    def snapshot(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        effect_id: UUID,
        for_update: bool = False,
    ) -> EffectAdminSnapshot | None:
        suffix = " FOR UPDATE OF effect,outbox" if for_update else ""
        row = transaction.execute(
            "SELECT effect.effect_id,effect.status,effect.current_attempt_id,effect.payload_digest,"
            "effect.action_intent_id,outbox.effect_outbox_item_id,delivery.delivery_id,delivery.receipt_digest "
            "FROM armi.effects AS effect JOIN armi.effect_outbox_items AS outbox ON outbox.effect_id=effect.effect_id "
            "LEFT JOIN armi.local_inbox_deliveries AS delivery ON delivery.effect_id=effect.effect_id "
            "AND delivery.payload_digest=effect.payload_digest WHERE effect.effect_id=%s"
            + suffix,
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
                cast(UUID, row[4]),
                cast(UUID, row[5]),
                cast(UUID | None, row[6]),
                None if row[7] is None else str(row[7]),
            )
        )

    def reconcile(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        snapshot: EffectAdminSnapshot,
        observation_id: UUID,
        observation_digest: str,
        completed: bool,
    ) -> bool:
        transaction.execute(
            "INSERT INTO armi.effect_observations (effect_observation_id,effect_id,effect_attempt_id,observation_kind,reliability,receiver_ref,observation_digest) VALUES (%s,%s,%s,'query','reliable',NULL,%s)",
            (
                observation_id,
                snapshot.effect_id,
                snapshot.attempt_id,
                observation_digest,
            ),
        )
        changed = transaction.execute(
            "UPDATE armi.effects SET status=%s,verification_status='verified',current_observation_id=%s,settled_at=statement_timestamp() WHERE effect_id=%s AND status='unknown'",
            (
                "completed" if completed else "failed",
                observation_id,
                snapshot.effect_id,
            ),
        ).rowcount
        outbox = transaction.execute(
            "UPDATE armi.effect_outbox_items SET status=%s,claim_owner=NULL,claim_expires_at=NULL,delivered_at=CASE WHEN %s THEN statement_timestamp() ELSE NULL END,last_error_code=%s WHERE effect_outbox_item_id=%s",
            (
                "delivered" if completed else "dead",
                completed,
                None if completed else "EFFECT-DELIVERY-NOT-FOUND",
                snapshot.outbox_id,
            ),
        ).rowcount
        return changed == 1 and outbox == 1

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
            "SELECT (SELECT count(*) FROM armi.effects WHERE payload_artifact_id=%s)+(SELECT count(*) FROM armi.local_inbox_deliveries WHERE payload_artifact_id=%s)",
            (artifact_id, artifact_id),
        ).fetchone()
        return 0 if row is None else int(cast(int, row[0]))


__all__ = ("PostgreSQLEffectAdmin",)
