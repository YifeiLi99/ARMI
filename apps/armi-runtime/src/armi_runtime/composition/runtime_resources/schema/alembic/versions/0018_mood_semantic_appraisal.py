"""Replace model-authored appraisal scores with semantic appraisal anchors."""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.mood_revisions
          DROP CONSTRAINT mood_revisions_payload_check,
          ADD CONSTRAINT mood_revisions_payload_check CHECK (
            (
              semantic_payload->>'schema_version'='armi.mood.v1'
              AND semantic_payload ?& ARRAY['emotions','mood','schema_version']
              AND semantic_payload
                    - ARRAY['emotions','mood','schema_version']::text[] = '{}'::jsonb
              AND jsonb_typeof(semantic_payload->'emotions')='array'
              AND jsonb_typeof(semantic_payload->'mood') IN ('string','null')
            ) OR (
              semantic_payload->>'schema_version'='armi.mood.v2'
              AND semantic_payload ?& ARRAY[
                    'dynamics_version','home_base','schema_version'
                  ]
              AND semantic_payload
                    - ARRAY[
                        'dynamics_version','home_base','schema_version'
                      ]::text[] = '{}'::jsonb
              AND semantic_payload->>'dynamics_version'='exponential.v1'
              AND jsonb_typeof(semantic_payload->'home_base')='object'
              AND (semantic_payload->'home_base')
                    ?& ARRAY['valence','arousal','dominance']
              AND (semantic_payload->'home_base')
                    - ARRAY['valence','arousal','dominance']::text[] = '{}'::jsonb
              AND (semantic_payload->'home_base'->>'valence')::integer
                    BETWEEN -100 AND 100
              AND (semantic_payload->'home_base'->>'arousal')::integer
                    BETWEEN -100 AND 100
              AND (semantic_payload->'home_base'->>'dominance')::integer
                    BETWEEN -100 AND 100
            ) OR (
              semantic_payload->>'schema_version'='armi.mood.v3'
              AND semantic_payload ?& ARRAY[
                    'dynamics_version','derivation_version','home_base','schema_version'
                  ]
              AND semantic_payload
                    - ARRAY[
                        'dynamics_version','derivation_version','home_base',
                        'schema_version'
                      ]::text[] = '{}'::jsonb
              AND semantic_payload->>'dynamics_version'='recency-reappraisal.v1'
              AND semantic_payload->>'derivation_version'
                    IN ('cpm-fuzzy.v1','cpm-fuzzy.v2')
              AND jsonb_typeof(semantic_payload->'home_base')='object'
              AND (semantic_payload->'home_base')
                    ?& ARRAY['valence','arousal','dominance']
              AND (semantic_payload->'home_base')
                    - ARRAY['valence','arousal','dominance']::text[] = '{}'::jsonb
              AND jsonb_typeof(semantic_payload->'home_base'->'valence')='number'
              AND jsonb_typeof(semantic_payload->'home_base'->'arousal')='number'
              AND jsonb_typeof(semantic_payload->'home_base'->'dominance')='number'
              AND (semantic_payload->'home_base'->>'valence')::integer
                    BETWEEN -100 AND 100
              AND (semantic_payload->'home_base'->>'arousal')::integer
                    BETWEEN -100 AND 100
              AND (semantic_payload->'home_base'->>'dominance')::integer
                    BETWEEN -100 AND 100
            )
          );

        ALTER TABLE armi.mood_appraisal_events
          ADD COLUMN appraisal_mapping_version text,
          ADD COLUMN derived_appraisal_payload jsonb;

        UPDATE armi.mood_appraisal_events
        SET appraisal_mapping_version='direct-scale.v1',
            derived_appraisal_payload=jsonb_build_object(
              'schema_version','armi.mood-derived-appraisal.v1',
              'vector',appraisal_payload->'appraisal'
            );

        ALTER TABLE armi.mood_appraisal_events
          ALTER COLUMN appraisal_mapping_version SET NOT NULL,
          ALTER COLUMN derived_appraisal_payload SET NOT NULL,
          DROP CONSTRAINT mood_appraisal_events_derivation_version_check,
          ADD CONSTRAINT mood_appraisal_events_derivation_version_check CHECK (
            derivation_version IN ('cpm-fuzzy.v1','cpm-fuzzy.v2')
          ),
          ADD CONSTRAINT mood_appraisal_events_semantic_version_check CHECK (
            (
              appraisal_payload->>'schema_version'='armi.mood-appraisal.v1'
              AND appraisal_mapping_version='direct-scale.v1'
              AND derived_appraisal_payload->>'schema_version'
                    ='armi.mood-derived-appraisal.v1'
              AND derivation_version='cpm-fuzzy.v1'
            ) OR (
              appraisal_payload->>'schema_version'='armi.mood-appraisal.v2'
              AND appraisal_mapping_version='semantic-anchors.v1'
              AND derived_appraisal_payload->>'schema_version'
                    ='armi.mood-derived-appraisal.v2'
              AND derivation_version='cpm-fuzzy.v2'
            )
          );

        DO $$
        DECLARE
          item record;
          new_revision_id uuid;
        BEGIN
          FOR item IN
            SELECT head.subject_id,head.current_revision_id,head.mood_version,
                   revision.semantic_payload
            FROM armi.mood_heads AS head
            JOIN armi.mood_revisions AS revision
              ON revision.mood_revision_id=head.current_revision_id
            WHERE revision.semantic_payload->>'schema_version'='armi.mood.v3'
              AND revision.semantic_payload->>'derivation_version'='cpm-fuzzy.v1'
          LOOP
            new_revision_id := uuidv7();
            INSERT INTO armi.mood_revisions
              (mood_revision_id,subject_id,mood_version,previous_revision_id,
               origin_kind,origin_ref,semantic_payload,privacy_scope)
            VALUES (
              new_revision_id,item.subject_id,item.mood_version+1,
              item.current_revision_id,'module_migration',item.current_revision_id,
              jsonb_set(
                item.semantic_payload,
                '{derivation_version}',
                to_jsonb('cpm-fuzzy.v2'::text)
              ),'private'
            );
            UPDATE armi.mood_heads
            SET current_revision_id=new_revision_id,
                mood_version=item.mood_version+1
            WHERE subject_id=item.subject_id;
          END LOOP;
        END
        $$;

        ALTER TABLE armi.cognitive_attempts
          DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
          ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
            candidate_schema_version IN (
              'armi.cognition-candidate.v1','armi.cognition-candidate.v2',
              'armi.cognition-candidate.v3','armi.cognition-candidate.v4',
              'armi.cognition-candidate.v5','armi.cognition-candidate.v6',
              'armi.cognition-candidate.v7',
              'armi.creator-dialogue-candidate.v5','armi.creator-dialogue-candidate.v6',
              'armi.creator-dialogue-candidate.v7','armi.creator-dialogue-candidate.v8',
              'armi.creator-dialogue-candidate.v9','armi.creator-dialogue-candidate.v10',
              'armi.creator-dialogue-candidate.v11','armi.creator-dialogue-candidate.v12',
              'armi.creator-dialogue-candidate.v13','armi.creator-dialogue-candidate.v14',
              'armi.creator-dialogue-candidate.v15','armi.creator-dialogue-candidate.v16',
              'armi.creator-dialogue-candidate.v17','armi.creator-dialogue-candidate.v18',
              'armi.creator-dialogue-candidate.v19','armi.creator-dialogue-candidate.v20',
              'armi.creator-dialogue-candidate.v21','armi.creator-dialogue-candidate.v22',
              'armi.creator-response-candidate.v1',
              'armi.creator-appraisal-candidate.v1',
              'armi.creator-appraisal-candidate.v2',
              'armi.creator-appraisal-candidate.v3',
              'armi.creator-appraisal-candidate.v4',
              'armi.autonomous-activity-candidate.v1',
              'armi.autonomous-activity-candidate.v2',
              'armi.autonomous-activity-candidate.v3',
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-attention-candidate.v3',
              'armi.activity-attention-candidate.v4',
              'armi.activity-internal-work-candidate.v1',
              'armi.activity-internal-work-candidate.v2',
              'armi.activity-internal-work-candidate.v3',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4',
              'armi.other-human-dialogue-candidate.v5',
              'armi.other-human-dialogue-candidate.v6'
            )
          );

        ALTER TABLE armi.cognitive_candidate_validations
          DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
          ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check
            CHECK (candidate_contract_version IN (
              'armi.cognition-candidate.v1','armi.cognition-candidate.v2',
              'armi.cognition-candidate.v3','armi.cognition-candidate.v4',
              'armi.cognition-candidate.v5','armi.cognition-candidate.v6',
              'armi.cognition-candidate.v7',
              'armi.creator-dialogue-candidate.v5','armi.creator-dialogue-candidate.v6',
              'armi.creator-dialogue-candidate.v7','armi.creator-dialogue-candidate.v8',
              'armi.creator-dialogue-candidate.v9','armi.creator-dialogue-candidate.v10',
              'armi.creator-dialogue-candidate.v11','armi.creator-dialogue-candidate.v12',
              'armi.creator-dialogue-candidate.v13','armi.creator-dialogue-candidate.v14',
              'armi.creator-dialogue-candidate.v15','armi.creator-dialogue-candidate.v16',
              'armi.creator-dialogue-candidate.v17','armi.creator-dialogue-candidate.v18',
              'armi.creator-dialogue-candidate.v19','armi.creator-dialogue-candidate.v20',
              'armi.creator-dialogue-candidate.v21','armi.creator-dialogue-candidate.v22',
              'armi.creator-dialogue-aggregate.v1',
              'armi.creator-dialogue-aggregate.v2',
              'armi.creator-dialogue-aggregate.v3',
              'armi.autonomous-activity-candidate.v1',
              'armi.autonomous-activity-candidate.v2',
              'armi.autonomous-activity-candidate.v3',
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-attention-candidate.v3',
              'armi.activity-attention-candidate.v4',
              'armi.activity-internal-work-candidate.v1',
              'armi.activity-internal-work-candidate.v2',
              'armi.activity-internal-work-candidate.v3',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4',
              'armi.other-human-dialogue-candidate.v5',
              'armi.other-human-dialogue-candidate.v6'
            ));
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
