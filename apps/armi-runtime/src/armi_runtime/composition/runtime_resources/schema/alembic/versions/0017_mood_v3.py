"""Install appraisal-driven Mood v3 and append-only episode trajectories."""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
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
              AND semantic_payload->>'derivation_version'='cpm-fuzzy.v1'
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

        CREATE TABLE armi.mood_appraisal_events (
          mood_appraisal_event_id uuid PRIMARY KEY
            CHECK (uuid_extract_version(mood_appraisal_event_id)=7),
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          mood_revision_id uuid NOT NULL,
          mood_episode_id uuid NOT NULL
            CHECK (uuid_extract_version(mood_episode_id)=7),
          previous_appraisal_event_id uuid,
          transition text NOT NULL
            CHECK (transition IN ('new','reinforce','reappraise','resolve')),
          event_phase text NOT NULL
            CHECK (event_phase IN ('anticipated','ongoing','realized','averted')),
          gist text NOT NULL
            CHECK (char_length(gist) BETWEEN 1 AND 64 AND gist=btrim(gist)),
          basis_ordinals smallint[] NOT NULL
            CHECK (cardinality(basis_ordinals) BETWEEN 1 AND 8),
          appraisal_payload jsonb NOT NULL
            CHECK (jsonb_typeof(appraisal_payload)='object'),
          importance smallint NOT NULL
            CHECK (importance BETWEEN 5 AND 100 AND importance % 5 = 0),
          derived_vad jsonb NOT NULL CHECK (jsonb_typeof(derived_vad)='object'),
          derived_components jsonb NOT NULL
            CHECK (jsonb_typeof(derived_components)='array'
                   AND jsonb_array_length(derived_components) BETWEEN 0 AND 3),
          derivation_version text NOT NULL CHECK (derivation_version='cpm-fuzzy.v1'),
          dynamics_version text NOT NULL
            CHECK (dynamics_version='recency-reappraisal.v1'),
          privacy_scope text NOT NULL CHECK (privacy_scope='private'),
          occurred_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          CONSTRAINT mood_appraisal_events_identity_key
            UNIQUE (mood_appraisal_event_id,subject_id),
          CONSTRAINT mood_appraisal_events_revision_key
            UNIQUE (mood_revision_id,subject_id),
          CONSTRAINT mood_appraisal_events_revision_fkey
            FOREIGN KEY (mood_revision_id,subject_id)
            REFERENCES armi.mood_revisions(mood_revision_id,subject_id),
          CONSTRAINT mood_appraisal_events_previous_fkey
            FOREIGN KEY (previous_appraisal_event_id,subject_id)
            REFERENCES armi.mood_appraisal_events(
              mood_appraisal_event_id,subject_id
            ),
          CONSTRAINT mood_appraisal_events_transition_shape_check CHECK (
            (transition='new' AND previous_appraisal_event_id IS NULL)
            OR (transition<>'new' AND previous_appraisal_event_id IS NOT NULL)
          )
        );

        CREATE UNIQUE INDEX mood_appraisal_events_previous_unique_idx
          ON armi.mood_appraisal_events(previous_appraisal_event_id)
          WHERE previous_appraisal_event_id IS NOT NULL;
        CREATE INDEX mood_appraisal_events_subject_time_idx
          ON armi.mood_appraisal_events(
            subject_id,occurred_at DESC,mood_appraisal_event_id DESC
          );
        CREATE INDEX mood_appraisal_events_episode_time_idx
          ON armi.mood_appraisal_events(
            subject_id,mood_episode_id,occurred_at DESC,mood_appraisal_event_id DESC
          );

        DO $$
        DECLARE
          item record;
          new_revision_id uuid;
        BEGIN
          FOR item IN
            SELECT head.subject_id,head.current_revision_id,head.mood_version,
                   revision.semantic_payload->'home_base' AS home_base
            FROM armi.mood_heads AS head
            JOIN armi.mood_revisions AS revision
              ON revision.mood_revision_id=head.current_revision_id
            WHERE revision.semantic_payload->>'schema_version'='armi.mood.v2'
          LOOP
            new_revision_id := uuidv7();
            INSERT INTO armi.mood_revisions
              (mood_revision_id,subject_id,mood_version,previous_revision_id,
               origin_kind,origin_ref,semantic_payload,privacy_scope)
            VALUES (
              new_revision_id,item.subject_id,item.mood_version+1,
              item.current_revision_id,'module_migration',item.current_revision_id,
              jsonb_build_object(
                'schema_version','armi.mood.v3',
                'dynamics_version','recency-reappraisal.v1',
                'derivation_version','cpm-fuzzy.v1',
                'home_base',item.home_base
              ),'private'
            );
            UPDATE armi.mood_heads
            SET current_revision_id=new_revision_id,
                mood_version=item.mood_version+1
            WHERE subject_id=item.subject_id;
          END LOOP;
        END
        $$;

        GRANT SELECT ON TABLE armi.mood_appraisal_events
          TO armi_runtime, armi_admin;
        GRANT INSERT ON TABLE armi.mood_appraisal_events TO armi_runtime;

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
              'armi.autonomous-activity-candidate.v1',
              'armi.autonomous-activity-candidate.v2',
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-attention-candidate.v3',
              'armi.activity-internal-work-candidate.v1',
              'armi.activity-internal-work-candidate.v2',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4',
              'armi.other-human-dialogue-candidate.v5'
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
              'armi.autonomous-activity-candidate.v1',
              'armi.autonomous-activity-candidate.v2',
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-attention-candidate.v3',
              'armi.activity-internal-work-candidate.v1',
              'armi.activity-internal-work-candidate.v2',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4',
              'armi.other-human-dialogue-candidate.v5'
            ));
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
