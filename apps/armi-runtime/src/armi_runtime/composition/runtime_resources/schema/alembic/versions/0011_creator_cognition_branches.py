"""Split Creator cognition into durable response and appraisal branches."""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE armi.cognitive_branches (
          cognitive_branch_id uuid PRIMARY KEY,
          cognitive_episode_id uuid NOT NULL
            REFERENCES armi.cognitive_episodes(cognitive_episode_id),
          branch_role text NOT NULL CHECK (
            branch_role IN ('primary','response_action','episode_appraisal')
          ),
          status text NOT NULL CHECK (
            status IN (
              'prepared','calling_model','succeeded','failed','timed_out',
              'cancelled','outcome_unknown'
            )
          ),
          selected_attempt_id uuid,
          response_artifact_id uuid REFERENCES armi.artifacts(artifact_id),
          failure_code text CHECK (
            failure_code IS NULL OR failure_code ~ '^MODEL-[A-Z0-9-]+$'
          ),
          created_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          settled_at timestamp(6) with time zone,
          CONSTRAINT cognitive_branches_id_check
            CHECK (uuid_extract_version(cognitive_branch_id)=7),
          CONSTRAINT cognitive_branches_episode_role_key
            UNIQUE (cognitive_episode_id,branch_role),
          CONSTRAINT cognitive_branches_state_check CHECK (
            (status IN ('prepared','calling_model')
             AND selected_attempt_id IS NULL AND response_artifact_id IS NULL
             AND failure_code IS NULL AND settled_at IS NULL)
            OR
            (status='succeeded' AND selected_attempt_id IS NOT NULL
             AND response_artifact_id IS NOT NULL AND failure_code IS NULL
             AND settled_at IS NOT NULL)
            OR
            (status IN ('failed','timed_out','cancelled','outcome_unknown')
             AND response_artifact_id IS NULL AND failure_code IS NOT NULL
             AND settled_at IS NOT NULL)
          )
        );

        INSERT INTO armi.cognitive_branches
          (cognitive_branch_id,cognitive_episode_id,branch_role,status,
           selected_attempt_id,response_artifact_id,failure_code,created_at,settled_at)
        SELECT uuidv7(),episode.cognitive_episode_id,'primary',
               CASE
                 WHEN attempt.result_status='succeeded' THEN 'succeeded'
                 WHEN attempt.result_status IN (
                   'timed_out','cancelled','outcome_unknown'
                 ) THEN attempt.result_status
                 WHEN attempt.result_status IS NOT NULL THEN 'failed'
                 WHEN episode.status='calling_model' THEN 'calling_model'
                 ELSE 'prepared'
               END,
               CASE WHEN attempt.result_status IS NOT NULL
                    THEN attempt.model_attempt_id END,
               CASE WHEN attempt.result_status='succeeded'
                    THEN attempt.response_artifact_id END,
               CASE
                 WHEN attempt.result_status IS NULL THEN NULL
                 WHEN attempt.result_status='succeeded' THEN NULL
                 ELSE COALESCE(attempt.error_code,'MODEL-PROVIDER-FAILED')
               END,
               episode.created_at,
               CASE WHEN attempt.result_status IS NOT NULL
                    THEN attempt.settled_at END
        FROM armi.cognitive_episodes AS episode
        LEFT JOIN LATERAL (
          SELECT candidate.* FROM armi.cognitive_attempts AS candidate
          WHERE candidate.cognitive_episode_id=episode.cognitive_episode_id
          ORDER BY candidate.attempt_no DESC LIMIT 1
        ) AS attempt ON true;

        ALTER TABLE armi.cognitive_attempts
          ADD COLUMN cognitive_branch_id uuid,
          ADD COLUMN late_response_artifact_id uuid
            REFERENCES armi.artifacts(artifact_id),
          ADD COLUMN late_observed_at timestamp(6) with time zone,
          ADD CONSTRAINT cognitive_attempts_late_response_shape_check CHECK (
            (late_response_artifact_id IS NULL)=(late_observed_at IS NULL)
          );

        UPDATE armi.cognitive_attempts AS attempt
        SET cognitive_branch_id=branch.cognitive_branch_id
        FROM armi.cognitive_branches AS branch
        WHERE branch.cognitive_episode_id=attempt.cognitive_episode_id
          AND branch.branch_role='primary';

        ALTER TABLE armi.cognitive_attempts
          ALTER COLUMN cognitive_branch_id SET NOT NULL,
          ADD CONSTRAINT cognitive_attempts_branch_fkey
            FOREIGN KEY (cognitive_branch_id)
            REFERENCES armi.cognitive_branches(cognitive_branch_id),
          DROP CONSTRAINT cognitive_attempts_cognitive_episode_id_attempt_no_key,
          DROP CONSTRAINT cognitive_attempts_work_id_work_attempt_id_key,
          ADD CONSTRAINT cognitive_attempts_branch_attempt_no_key
            UNIQUE (cognitive_branch_id,attempt_no);

        ALTER TABLE armi.cognitive_branches
          ADD CONSTRAINT cognitive_branches_selected_attempt_fkey
            FOREIGN KEY (selected_attempt_id)
            REFERENCES armi.cognitive_attempts(model_attempt_id);

        CREATE INDEX cognitive_branches_episode_status_idx
          ON armi.cognitive_branches(cognitive_episode_id,status,branch_role);
        CREATE INDEX cognitive_attempts_branch_status_idx
          ON armi.cognitive_attempts(cognitive_branch_id,dispatch_status,attempt_no);

        CREATE TABLE armi.cognitive_dialogue_aggregates (
          cognitive_episode_id uuid PRIMARY KEY
            REFERENCES armi.cognitive_episodes(cognitive_episode_id),
          aggregate_outcome text NOT NULL CHECK (
            aggregate_outcome IN ('complete','response_only','internal_only')
          ),
          response_branch_id uuid REFERENCES armi.cognitive_branches(cognitive_branch_id),
          appraisal_branch_id uuid REFERENCES armi.cognitive_branches(cognitive_branch_id),
          primary_model_attempt_id uuid NOT NULL
            REFERENCES armi.cognitive_attempts(model_attempt_id),
          aggregate_artifact_id uuid NOT NULL REFERENCES armi.artifacts(artifact_id),
          response_kind text,
          created_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          CONSTRAINT cognitive_dialogue_aggregates_shape_check CHECK (
            (aggregate_outcome='complete' AND response_branch_id IS NOT NULL
             AND appraisal_branch_id IS NOT NULL AND response_kind IS NOT NULL)
            OR
            (aggregate_outcome='response_only' AND response_branch_id IS NOT NULL
             AND appraisal_branch_id IS NULL AND response_kind IS NOT NULL)
            OR
            (aggregate_outcome='internal_only' AND response_branch_id IS NULL
             AND appraisal_branch_id IS NOT NULL AND response_kind IS NULL)
          )
        );

        CREATE TABLE armi.cognition_maintenance_cursors (
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          life_generation_id uuid NOT NULL
            REFERENCES armi.life_generations(life_generation_id),
          last_experience_id uuid REFERENCES armi.accepted_experiences(experience_id),
          processed_through_experience_id uuid
            REFERENCES armi.accepted_experiences(experience_id),
          dirty_since timestamp(6) with time zone,
          updated_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          PRIMARY KEY (subject_id,life_generation_id),
          CONSTRAINT cognition_maintenance_cursors_dirty_check CHECK (
            (dirty_since IS NULL AND processed_through_experience_id IS NULL)
            OR (dirty_since IS NOT NULL AND last_experience_id IS NOT NULL)
          )
        );

        CREATE TABLE armi.cognition_maintenance_batches (
          maintenance_batch_id uuid PRIMARY KEY,
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          life_generation_id uuid NOT NULL
            REFERENCES armi.life_generations(life_generation_id),
          trigger_kind text NOT NULL CHECK (trigger_kind IN ('runtime_idle','sleep')),
          status text NOT NULL CHECK (
            status IN ('prepared','running','completed','interrupted','failed')
          ),
          base_subject_version bigint NOT NULL CHECK (base_subject_version>=0),
          failure_code text,
          created_at timestamp(6) with time zone NOT NULL
            DEFAULT statement_timestamp(),
          finished_at timestamp(6) with time zone,
          CONSTRAINT cognition_maintenance_batches_id_check
            CHECK (uuid_extract_version(maintenance_batch_id)=7),
          CONSTRAINT cognition_maintenance_batches_state_check CHECK (
            (status IN ('prepared','running') AND failure_code IS NULL
             AND finished_at IS NULL)
            OR
            (status='completed' AND failure_code IS NULL AND finished_at IS NOT NULL)
            OR
            (status IN ('interrupted','failed') AND failure_code IS NOT NULL
             AND finished_at IS NOT NULL)
          )
        );

        CREATE UNIQUE INDEX cognition_maintenance_batches_active_idx
          ON armi.cognition_maintenance_batches(subject_id,life_generation_id)
          WHERE status IN ('prepared','running');

        CREATE TABLE armi.cognition_maintenance_batch_sources (
          maintenance_batch_id uuid NOT NULL
            REFERENCES armi.cognition_maintenance_batches(maintenance_batch_id),
          experience_id uuid NOT NULL
            REFERENCES armi.accepted_experiences(experience_id),
          ordinal smallint NOT NULL CHECK (ordinal BETWEEN 1 AND 64),
          PRIMARY KEY (maintenance_batch_id,experience_id),
          UNIQUE (maintenance_batch_id,ordinal)
        );

        ALTER TABLE armi.cognitive_episodes
          DROP CONSTRAINT cognitive_episodes_purpose_check,
          ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task',
            'consider_codex_result','consider_autonomous_life',
            'consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','reflect_self','reflect_mind','reflect_prompt',
            'consider_creator_outreach','consider_other_human_input'
          )),
          DROP CONSTRAINT cognitive_episodes_scene_shape_check,
          ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
            (purpose IN (
              'consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep',
              'maintain_subjective_memory','perform_subject_self_check',
              'reflect_self','reflect_mind','reflect_prompt'
             ) AND scene_id IS NULL AND context_party_id IS NULL)
            OR
            (purpose NOT IN (
              'consider_autonomous_life','consider_activity_attention',
              'consider_activity_internal_work','consider_sleep',
              'maintain_subjective_memory','perform_subject_self_check',
              'reflect_self','reflect_mind','reflect_prompt'
             ) AND scene_id IS NOT NULL AND context_party_id IS NOT NULL)
          );

        ALTER TABLE armi.opportunities
          DROP CONSTRAINT opportunities_purpose_check,
          ADD CONSTRAINT opportunities_purpose_check CHECK (purpose IN (
            'consider_creator_input','consider_web_evidence','consider_codex_task',
            'consider_codex_result','consider_autonomous_life',
            'consider_activity_attention','consider_activity_internal_work',
            'consider_sleep','consider_life_query_result','maintain_subjective_memory',
            'perform_subject_self_check','reflect_self','reflect_mind','reflect_prompt',
            'consider_creator_outreach','consider_other_human_input'
          ));

        ALTER TABLE armi.maintenance_session_revisions
          DROP CONSTRAINT maintenance_session_revisions_phase_check,
          ADD CONSTRAINT maintenance_session_revisions_phase_check CHECK (phase IN (
            'preparing','memory_maintenance','self_check','reflect_self',
            'reflect_mind','reflect_prompt','life_quiet','resume_check','completed'
          ));

        ALTER TABLE armi.maintenance_phase_results
          ADD COLUMN issue_target text,
          ADD CONSTRAINT maintenance_phase_results_issue_target_value_check
            CHECK (
              issue_target IS NULL OR issue_target IN ('self','mind','prompt')
            );

        UPDATE armi.maintenance_phase_results
          SET issue_target='self' WHERE outcome='issue_found';

        ALTER TABLE armi.maintenance_phase_results
          ADD CONSTRAINT maintenance_phase_results_issue_target_check CHECK (
            (outcome='issue_found')=(issue_target IS NOT NULL)
          ),
          DROP CONSTRAINT maintenance_phase_results_check,
          ADD CONSTRAINT maintenance_phase_results_check CHECK (
            (phase='memory_maintenance'
             AND outcome IN ('memory_changed','memory_unchanged'))
            OR (phase='self_check' AND outcome IN ('issue_found','no_issue'))
            OR (phase IN ('reflect_self','reflect_mind','reflect_prompt')
                AND outcome IN ('reflection_changed','reflection_unchanged'))
          ),
          DROP CONSTRAINT maintenance_phase_results_outcome_check,
          ADD CONSTRAINT maintenance_phase_results_outcome_check CHECK (outcome IN (
            'memory_changed','memory_unchanged','issue_found','no_issue',
            'reflection_changed','reflection_unchanged'
          )),
          DROP CONSTRAINT maintenance_phase_results_phase_check,
          ADD CONSTRAINT maintenance_phase_results_phase_check CHECK (phase IN (
            'memory_maintenance','self_check','reflect_self','reflect_mind','reflect_prompt'
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
              'armi.creator-response-candidate.v1','armi.creator-appraisal-candidate.v1',
              'armi.autonomous-activity-candidate.v1',
              'armi.activity-attention-candidate.v1','armi.activity-attention-candidate.v2',
              'armi.activity-internal-work-candidate.v1','armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4'
            )
          ),
          DROP CONSTRAINT cognitive_attempts_profile_check,
          ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
            profile IN (
              'creator_input_cognition','creator_dialogue','creator_response',
              'creator_appraisal','creator_outreach','other_human_dialogue',
              'autonomous_activity','activity_attention','activity_internal_work',
              'sleep_decision','memory_maintenance','subject_self_check',
              'reflect_self','reflect_mind','reflect_prompt',
              'web_evidence_cognition','codex_task','codex_result'
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
              'armi.autonomous-activity-candidate.v1',
              'armi.activity-attention-candidate.v1','armi.activity-attention-candidate.v2',
              'armi.activity-internal-work-candidate.v1','armi.sleep-decision-candidate.v1',
              'armi.maintenance-work-candidate.v1',
              'armi.owner-reflection-candidate.v1',
              'armi.other-human-dialogue-candidate.v1',
              'armi.other-human-dialogue-candidate.v2',
              'armi.other-human-dialogue-candidate.v3',
              'armi.other-human-dialogue-candidate.v4'
            ));

        GRANT SELECT,INSERT,UPDATE ON armi.cognitive_branches,
          armi.cognitive_dialogue_aggregates,
          armi.cognition_maintenance_cursors,
          armi.cognition_maintenance_batches,
          armi.cognition_maintenance_batch_sources TO armi_runtime;
        GRANT SELECT ON armi.cognitive_branches,armi.cognitive_dialogue_aggregates,
          armi.cognition_maintenance_cursors,armi.cognition_maintenance_batches,
          armi.cognition_maintenance_batch_sources TO armi_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
