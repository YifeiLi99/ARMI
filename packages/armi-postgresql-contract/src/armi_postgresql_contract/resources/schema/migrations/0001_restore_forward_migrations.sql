-- 0000 was mutable before forward migrations were restored. The gateway only
-- admits verified, known source identities; fresh 0000 already has these columns.
ALTER TABLE armi.autonomy_plans
    ADD COLUMN IF NOT EXISTS consumed_activity_conditions jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE armi.autonomy_plans
    DROP CONSTRAINT IF EXISTS autonomy_plans_consumed_activity_conditions_check,
    ADD CONSTRAINT autonomy_plans_consumed_activity_conditions_check
        CHECK (jsonb_typeof(consumed_activity_conditions)='array'),
    DROP CONSTRAINT autonomy_plans_last_direction_check,
    ADD CONSTRAINT autonomy_plans_last_direction_check
        CHECK (last_direction IN ('rest','reflect','continue','explore','connect','undetermined'));

ALTER TABLE armi.cognitive_episodes
    ADD COLUMN IF NOT EXISTS maintenance_decision_basis jsonb;
ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_maintenance_result_shape,
    ADD CONSTRAINT cognitive_episodes_maintenance_result_shape CHECK (
        (maintenance_session_id IS NULL AND maintenance_phase_id IS NULL AND maintenance_head_version IS NULL AND maintenance_phase IS NULL AND maintenance_outcome IS NULL AND maintenance_result_summary IS NULL AND maintenance_decision_basis IS NULL AND maintenance_creator_visible_problem IS NULL AND maintenance_memory_id IS NULL AND maintenance_issue_target IS NULL AND maintenance_completed_at IS NULL)
        OR (maintenance_session_id IS NOT NULL AND maintenance_phase_id IS NOT NULL AND maintenance_head_version IS NOT NULL AND maintenance_head_version > 0 AND maintenance_phase IS NOT NULL AND maintenance_outcome IS NOT NULL AND (maintenance_result_summary IS NOT NULL OR maintenance_decision_basis IS NOT NULL) AND maintenance_completed_at IS NOT NULL AND candidate_application_id IS NOT NULL AND subject_commit_id IS NOT NULL)),
    DROP CONSTRAINT IF EXISTS cognitive_episodes_maintenance_basis_shape,
    ADD CONSTRAINT cognitive_episodes_maintenance_basis_shape CHECK (maintenance_decision_basis IS NULL OR (jsonb_typeof(maintenance_decision_basis)='object' AND maintenance_decision_basis ?& ARRAY['reason_code','basis_refs'] AND jsonb_typeof(maintenance_decision_basis->'reason_code')='string' AND jsonb_typeof(maintenance_decision_basis->'basis_refs')='array' AND jsonb_array_length(maintenance_decision_basis->'basis_refs') BETWEEN 1 AND 8));

ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_check,
    ADD CONSTRAINT opportunities_check CHECK (
        autonomy_category IS NULL OR (
            source_kind='autonomy_plan'
            AND purpose IN ('consider_autonomy_check','consider_autonomous_life')
            AND autonomy_category IN ('rest','reflect','continue','explore','connect','undetermined')
            AND (autonomy_category<>'wait' OR purpose='consider_autonomy_check')
        )
    );
