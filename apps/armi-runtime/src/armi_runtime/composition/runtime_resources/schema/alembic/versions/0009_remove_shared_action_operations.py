"""Move operation identity to Expression facts and remove the shared ledger."""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.action_intents
          ADD COLUMN operation_ref uuid;
        ALTER TABLE armi.dialogue_decisions
          ADD COLUMN operation_ref uuid;

        UPDATE armi.action_intents AS intent
           SET operation_ref = operation.operation_id
          FROM armi.action_operations AS operation
         WHERE operation.action_intent_id = intent.action_intent_id;

        UPDATE armi.dialogue_decisions AS decision
           SET operation_ref = operation.operation_id
          FROM armi.action_operations AS operation
         WHERE operation.dialogue_decision_id = decision.dialogue_decision_id;

        DO $validation$
        BEGIN
          IF EXISTS (
            SELECT operation.operation_id
              FROM armi.action_operations AS operation
             WHERE operation.action_intent_id IS NULL
               AND operation.dialogue_decision_id IS NULL
          ) THEN
            RAISE EXCEPTION 'action operation has no Expression owner';
          END IF;

          IF EXISTS (
            SELECT operation.action_intent_id
              FROM armi.action_operations AS operation
             WHERE operation.action_intent_id IS NOT NULL
             GROUP BY operation.action_intent_id
            HAVING count(*) <> 1
          ) OR EXISTS (
            SELECT operation.dialogue_decision_id
              FROM armi.action_operations AS operation
             WHERE operation.dialogue_decision_id IS NOT NULL
             GROUP BY operation.dialogue_decision_id
            HAVING count(*) <> 1
          ) THEN
            RAISE EXCEPTION 'Expression fact maps to multiple action operations';
          END IF;

          IF EXISTS (
            SELECT intent.action_intent_id
              FROM armi.action_intents AS intent
             WHERE intent.operation_ref IS NULL
          ) OR EXISTS (
            SELECT decision.dialogue_decision_id
              FROM armi.dialogue_decisions AS decision
             WHERE decision.operation_ref IS NULL
          ) THEN
            RAISE EXCEPTION 'Expression fact is missing an action operation';
          END IF;

          IF EXISTS (
            SELECT decision.dialogue_decision_id
              FROM armi.dialogue_decisions AS decision
              JOIN armi.action_intents AS intent
                ON intent.action_intent_id = decision.action_intent_id
             WHERE decision.action_intent_id IS NOT NULL
               AND decision.operation_ref <> intent.operation_ref
          ) THEN
            RAISE EXCEPTION 'dialogue and action intent operation identity conflicts';
          END IF;
        END
        $validation$;

        ALTER TABLE armi.action_intents
          ALTER COLUMN operation_ref SET NOT NULL,
          ADD CONSTRAINT action_intents_operation_ref_check
            CHECK (uuid_extract_version(operation_ref) = 7),
          ADD CONSTRAINT action_intents_operation_ref_key UNIQUE (operation_ref),
          ADD CONSTRAINT action_intents_operation_owner_key
            UNIQUE (action_intent_id, operation_ref);

        ALTER TABLE armi.dialogue_decisions
          ALTER COLUMN operation_ref SET NOT NULL,
          ADD CONSTRAINT dialogue_decisions_operation_ref_check
            CHECK (uuid_extract_version(operation_ref) = 7),
          ADD CONSTRAINT dialogue_decisions_operation_ref_key UNIQUE (operation_ref),
          ADD CONSTRAINT dialogue_decisions_intent_operation_fkey
            FOREIGN KEY (action_intent_id, operation_ref)
            REFERENCES armi.action_intents(action_intent_id, operation_ref);

        ALTER TABLE armi.effects
          DROP CONSTRAINT effects_policy_owner_fkey,
          DROP CONSTRAINT effects_operation_owner_fkey;
        ALTER TABLE armi.policy_decisions
          DROP CONSTRAINT policy_decisions_effect_owner_key,
          DROP CONSTRAINT policy_decisions_operation_id_fkey;

        ALTER TABLE armi.policy_decisions
          DROP COLUMN operation_id,
          ADD CONSTRAINT policy_decisions_effect_owner_key
            UNIQUE (policy_decision_id, action_intent_revision_id);

        ALTER TABLE armi.effects
          DROP COLUMN operation_id,
          ADD CONSTRAINT effects_action_intent_owner_fkey
            FOREIGN KEY (
              action_intent_id, subject_id, scene_id, context_party_id
            ) REFERENCES armi.action_intents(
              action_intent_id, subject_id, scene_id, context_party_id
            ),
          ADD CONSTRAINT effects_policy_owner_fkey
            FOREIGN KEY (policy_decision_id, action_intent_revision_id)
            REFERENCES armi.policy_decisions(
              policy_decision_id, action_intent_revision_id
            );

        DROP TABLE armi.action_operations;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
