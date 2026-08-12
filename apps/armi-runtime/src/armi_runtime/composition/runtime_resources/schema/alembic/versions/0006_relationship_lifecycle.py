"""Upgrade relationship ownership to lifecycle v2."""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $validation$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM armi.relationship_revisions AS revision
            CROSS JOIN LATERAL jsonb_array_elements(revision.facts) AS fact(value)
            WHERE jsonb_typeof(revision.facts) <> 'array'
               OR jsonb_typeof(fact.value) <> 'object'
               OR NOT (fact.value ? 'kind' AND fact.value ? 'summary')
               OR (SELECT array_agg(key ORDER BY key)
                   FROM jsonb_object_keys(fact.value) AS key)
                  <> ARRAY['kind', 'summary']::text[]
               OR jsonb_typeof(fact.value->'kind') <> 'string'
               OR jsonb_typeof(fact.value->'summary') <> 'string'
               OR fact.value->>'kind' NOT IN (
                    'shared_experience', 'party_expression'
                  )
               OR length(fact.value->>'summary') NOT BETWEEN 1 AND 512
          ) THEN
            RAISE EXCEPTION 'invalid legacy relationship facts';
          END IF;

          IF EXISTS (
            SELECT 1 FROM armi.relationship_revisions
            WHERE mechanism_identity <> 'armi.relationship.contextual-v1'
          ) THEN
            RAISE EXCEPTION 'unknown legacy relationship mechanism';
          END IF;
        END
        $validation$;

        CREATE TABLE armi.relationship_fact_identity_0006 AS
        SELECT relationship_id, kind, summary, uuidv7() AS fact_id
        FROM (
          SELECT DISTINCT revision.relationship_id,
                 fact.value->>'kind' AS kind,
                 fact.value->>'summary' AS summary
          FROM armi.relationship_revisions AS revision
          CROSS JOIN LATERAL jsonb_array_elements(revision.facts) AS fact(value)
        ) AS legacy;

        UPDATE armi.relationship_revisions AS revision
        SET facts = rewritten.facts
        FROM (
          SELECT source.relationship_revision_id,
                 jsonb_agg(
                   jsonb_build_object(
                     'fact_id', identity.fact_id::text,
                     'kind', fact.value->>'kind',
                     'summary', fact.value->>'summary'
                   ) ORDER BY fact.ordinality
                 ) AS facts
          FROM armi.relationship_revisions AS source
          CROSS JOIN LATERAL jsonb_array_elements(source.facts)
            WITH ORDINALITY AS fact(value, ordinality)
          JOIN armi.relationship_fact_identity_0006 AS identity
            ON identity.relationship_id = source.relationship_id
           AND identity.kind = fact.value->>'kind'
           AND identity.summary = fact.value->>'summary'
          GROUP BY source.relationship_revision_id
        ) AS rewritten
        WHERE rewritten.relationship_revision_id = revision.relationship_revision_id;

        DROP TABLE armi.relationship_fact_identity_0006;

        ALTER TABLE armi.relationship_revisions
          ADD COLUMN issue_resolution jsonb,
          ADD CONSTRAINT relationship_revisions_issue_resolution_check
            CHECK (
              issue_resolution IS NULL OR (
                jsonb_typeof(issue_resolution) = 'object'
                AND issue_resolution ?&
                    ARRAY['issue_id', 'resolution_summary', 'status']::text[]
                AND issue_resolution
                    - ARRAY['issue_id', 'resolution_summary', 'status']::text[]
                    = '{}'::jsonb
                AND issue_resolution->>'status' = 'resolved'
                AND (issue_resolution->>'issue_id')::uuid IS NOT NULL
                AND uuid_extract_version(
                      (issue_resolution->>'issue_id')::uuid
                    ) = 7
                AND length(issue_resolution->>'resolution_summary')
                    BETWEEN 1 AND 512
              )
            );

        ALTER TABLE armi.relationship_revisions
          DROP CONSTRAINT relationship_revisions_mechanism_identity_check,
          ADD CONSTRAINT relationship_revisions_mechanism_identity_check
            CHECK (mechanism_identity IN (
              'armi.relationship.contextual-v1',
              'armi.relationship.lifecycle-v2'
            ));

        ALTER TABLE armi.relationships
          ADD COLUMN tombstoned_at timestamp(6) with time zone,
          ADD COLUMN tombstone_order_id uuid,
          ADD CONSTRAINT relationships_tombstone_pair_check
            CHECK ((tombstoned_at IS NULL) = (tombstone_order_id IS NULL)),
          ADD CONSTRAINT relationships_tombstone_order_id_check
            CHECK (
              tombstone_order_id IS NULL
              OR uuid_extract_version(tombstone_order_id) = 7
            ),
          ADD CONSTRAINT relationships_tombstone_order_id_fkey
            FOREIGN KEY (tombstone_order_id)
            REFERENCES armi.deletion_orders(deletion_order_id);

        WITH first_tombstone AS (
          SELECT DISTINCT ON (item.target_ref)
                 item.target_ref AS relationship_id,
                 item.deletion_order_id,
                 item.completed_at
          FROM armi.deletion_items AS item
          WHERE item.target_kind = 'relationship'
            AND item.result_status IN ('completed', 'partial')
          ORDER BY item.target_ref, item.completed_at, item.deletion_item_id
        )
        UPDATE armi.relationships AS relationship
        SET tombstoned_at = first_tombstone.completed_at,
            tombstone_order_id = first_tombstone.deletion_order_id
        FROM first_tombstone
        WHERE first_tombstone.relationship_id = relationship.relationship_id;

        CREATE INDEX relationships_active_other_party_idx
          ON armi.relationships (other_party_id, scope)
          WHERE tombstoned_at IS NULL;

        GRANT UPDATE(tombstoned_at, tombstone_order_id)
          ON TABLE armi.relationships TO armi_runtime;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
