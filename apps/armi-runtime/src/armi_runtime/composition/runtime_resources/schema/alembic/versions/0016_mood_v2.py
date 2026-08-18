"""Install numerical mood dynamics and append-only affective events."""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.mood_revisions
          DROP CONSTRAINT mood_revisions_origin_check,
          DROP CONSTRAINT mood_revisions_payload_check,
          ADD CONSTRAINT mood_revisions_origin_check CHECK (
            (origin_kind='bootstrap' AND mood_version=1
             AND previous_revision_id IS NULL
             AND subject_commit_id IS NULL AND proposal_ref IS NULL)
            OR
            (origin_kind='module_migration'
             AND subject_commit_id IS NULL AND proposal_ref IS NULL
             AND ((mood_version=1 AND previous_revision_id IS NULL)
                  OR (mood_version>1 AND previous_revision_id IS NOT NULL)))
            OR
            (origin_kind='subject_commit' AND mood_version>1
             AND previous_revision_id IS NOT NULL
             AND subject_commit_id IS NOT NULL AND proposal_ref IS NOT NULL)
            OR
            (origin_kind='admin_correction' AND mood_version>1
             AND previous_revision_id IS NOT NULL
             AND subject_commit_id IS NULL AND proposal_ref IS NULL)
          ),
          ADD CONSTRAINT mood_revisions_payload_check CHECK (
            (
              semantic_payload->>'schema_version'='armi.mood.v1'
              AND semantic_payload ?& ARRAY['emotions','mood','schema_version']
              AND semantic_payload
                    - ARRAY['emotions','mood','schema_version']::text[] = '{}'::jsonb
              AND jsonb_typeof(semantic_payload->'emotions')='array'
              AND jsonb_typeof(semantic_payload->'mood') IN ('string','null')
            )
            OR
            (
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

        CREATE TABLE armi.mood_affective_events (
          mood_affective_event_id uuid PRIMARY KEY
            CHECK (uuid_extract_version(mood_affective_event_id)=7),
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          mood_revision_id uuid NOT NULL,
          importance smallint NOT NULL
            CHECK (importance BETWEEN 5 AND 100 AND importance % 5 = 0),
          components jsonb NOT NULL
            CHECK (jsonb_typeof(components)='array'
                   AND jsonb_array_length(components) BETWEEN 1 AND 3),
          privacy_scope text NOT NULL CHECK (privacy_scope='private'),
          occurred_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          CONSTRAINT mood_affective_events_revision_key
            UNIQUE (mood_revision_id,subject_id),
          CONSTRAINT mood_affective_events_revision_fkey
            FOREIGN KEY (mood_revision_id,subject_id)
            REFERENCES armi.mood_revisions(mood_revision_id,subject_id)
        );

        CREATE INDEX mood_affective_events_subject_time_idx
          ON armi.mood_affective_events(
            subject_id,occurred_at DESC,mood_affective_event_id DESC
          );

        DO $$
        DECLARE
          item record;
          new_revision_id uuid;
        BEGIN
          FOR item IN
            SELECT subject_id,current_revision_id,mood_version
            FROM armi.mood_heads
          LOOP
            new_revision_id := uuidv7();
            INSERT INTO armi.mood_revisions
              (mood_revision_id,subject_id,mood_version,previous_revision_id,
               origin_kind,origin_ref,semantic_payload,privacy_scope)
            VALUES (
              new_revision_id,item.subject_id,item.mood_version+1,
              item.current_revision_id,'module_migration',item.current_revision_id,
              jsonb_build_object(
                'schema_version','armi.mood.v2',
                'dynamics_version','exponential.v1',
                'home_base',jsonb_build_object(
                  'valence',0,'arousal',0,'dominance',0
                )
              ),
              'private'
            );
            UPDATE armi.mood_heads
            SET current_revision_id=new_revision_id,
                mood_version=item.mood_version+1
            WHERE subject_id=item.subject_id;
          END LOOP;
        END
        $$;

        GRANT SELECT ON TABLE armi.mood_affective_events
          TO armi_runtime, armi_admin;
        GRANT INSERT ON TABLE armi.mood_affective_events TO armi_runtime;

        ALTER TABLE armi.cognitive_episodes
          DROP CONSTRAINT cognitive_episodes_purpose_check,
          ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task',
            'consider_codex_result','consider_autonomous_life',
            'consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','reflect_self','reflect_mind','reflect_mood',
            'reflect_prompt','consider_creator_outreach','consider_other_human_input'
          )),
          DROP CONSTRAINT cognitive_episodes_scene_shape_check,
          ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
            (purpose IN (
              'consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep',
              'maintain_subjective_memory','perform_subject_self_check',
              'reflect_self','reflect_mind','reflect_mood','reflect_prompt'
             ) AND scene_id IS NULL AND context_party_id IS NULL)
            OR
            (purpose NOT IN (
              'consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep',
              'maintain_subjective_memory','perform_subject_self_check',
              'reflect_self','reflect_mind','reflect_mood','reflect_prompt'
             ) AND scene_id IS NOT NULL AND context_party_id IS NOT NULL)
          );

        ALTER TABLE armi.opportunities
          DROP CONSTRAINT opportunities_purpose_check,
          ADD CONSTRAINT opportunities_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task',
            'consider_codex_result','consider_autonomous_life',
            'consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','reflect_self','reflect_mind','reflect_mood',
            'reflect_prompt','consider_creator_outreach','consider_other_human_input'
          ));

        ALTER TABLE armi.maintenance_session_revisions
          DROP CONSTRAINT maintenance_session_revisions_phase_check,
          ADD CONSTRAINT maintenance_session_revisions_phase_check CHECK (phase IN (
            'preparing','memory_maintenance','self_check','reflect_self',
            'reflect_mind','reflect_mood','reflect_prompt','life_quiet',
            'resume_check','completed'
          ));

        ALTER TABLE armi.maintenance_phase_results
          DROP CONSTRAINT maintenance_phase_results_check,
          ADD CONSTRAINT maintenance_phase_results_check CHECK (
            (phase='memory_maintenance'
             AND outcome IN ('memory_changed','memory_unchanged'))
            OR (phase='self_check' AND outcome IN ('issue_found','no_issue'))
            OR (phase IN (
                  'reflect_self','reflect_mind','reflect_mood','reflect_prompt'
                ) AND outcome IN ('reflection_changed','reflection_unchanged'))
          ),
          DROP CONSTRAINT maintenance_phase_results_phase_check,
          ADD CONSTRAINT maintenance_phase_results_phase_check CHECK (phase IN (
            'memory_maintenance','self_check','reflect_self','reflect_mind',
            'reflect_mood','reflect_prompt'
          ));

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
              'armi.autonomous-activity-candidate.v1',
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-internal-work-candidate.v1',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4'
            )
          ),
          DROP CONSTRAINT cognitive_attempts_profile_check,
          ADD CONSTRAINT cognitive_attempts_profile_check CHECK (profile IN (
            'creator_input_cognition','creator_dialogue','creator_response',
            'creator_appraisal','creator_outreach','other_human_dialogue',
            'autonomous_activity','activity_attention','activity_internal_work',
            'sleep_decision','memory_maintenance','subject_self_check',
            'reflect_self','reflect_mind','reflect_mood','reflect_prompt',
            'web_evidence_cognition','codex_task','codex_result'
          ));

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
              'armi.activity-attention-candidate.v1',
              'armi.activity-attention-candidate.v2',
              'armi.activity-internal-work-candidate.v1',
              'armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4'
            ));
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
