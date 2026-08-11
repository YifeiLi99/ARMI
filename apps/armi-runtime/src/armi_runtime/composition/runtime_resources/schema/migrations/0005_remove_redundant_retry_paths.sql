-- Make durable work the sole internal retry owner and remove its unused outbox mirror.

DROP TABLE armi.outbox_items;

ALTER TABLE armi.web_observation_requests
    DROP COLUMN max_attempts;

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_attempt_no_check,
    ADD CONSTRAINT cognitive_attempts_attempt_no_check CHECK (attempt_no >= 1);

ALTER TABLE armi.observation_attempts
    DROP CONSTRAINT observation_attempts_attempt_no_check,
    ADD CONSTRAINT observation_attempts_attempt_no_check CHECK (attempt_no >= 1);

DELETE FROM armi.runtime_recovery_metrics
WHERE metric_kind IN (
    'requeued_outbox_count',
    'dead_outbox_count',
    'resumable_outbox_count'
);

ALTER TABLE armi.runtime_recovery_metrics
    DROP CONSTRAINT runtime_recovery_metrics_kind_check,
    ADD CONSTRAINT runtime_recovery_metrics_kind_check CHECK (
        metric_kind = ANY (ARRAY[
            'requeued_work_count', 'terminal_work_count',
            'resumable_work_count', 'critical_artifact_count',
            'resumable_opportunity_count', 'resumable_cognitive_episode_count',
            'resumable_model_attempt_count',
            'resumable_candidate_validation_count',
            'resumable_subject_commit_count',
            'resumable_capability_request_count',
            'resumable_response_operation_count', 'resumable_effect_count',
            'resumable_effect_outbox_count', 'resumable_effect_attempt_count',
            'reliable_effect_observation_count',
            'creator_response_delivery_count',
            'resumable_web_observation_count',
            'unknown_web_observation_attempt_count',
            'resumable_web_research_intent_count',
            'pending_web_evidence_acceptance_count',
            'resumable_web_cognition_count',
            'resumable_admin_correction_work_count',
            'resumable_codex_task_count', 'resumable_codex_effect_count',
            'pending_codex_result_acceptance_count'
        ])
    );

ALTER TABLE armi.exact_life_query_intents
    DROP CONSTRAINT exact_life_query_intents_check,
    ADD CONSTRAINT exact_life_query_intents_check CHECK (
        (status = 'pending' AND result_artifact_id IS NULL
            AND result_count IS NULL AND failure_code IS NULL
            AND result_opportunity_id IS NULL AND completed_at IS NULL)
        OR (status IN ('succeeded', 'empty') AND result_artifact_id IS NOT NULL
            AND result_count IS NOT NULL AND failure_code IS NULL
            AND result_opportunity_id IS NOT NULL AND completed_at IS NOT NULL)
        OR (status IN ('failed', 'denied') AND result_count = 0
            AND failure_code IS NOT NULL AND completed_at IS NOT NULL
            AND (
                (result_artifact_id IS NOT NULL
                    AND result_opportunity_id IS NOT NULL)
                OR (status = 'failed' AND result_artifact_id IS NULL
                    AND result_opportunity_id IS NULL)
            ))
    );

ALTER TABLE armi.web_research_intents
    DROP CONSTRAINT web_research_intents_check,
    ADD CONSTRAINT web_research_intents_check CHECK (
        (status = 'pending' AND web_observation_request_id IS NULL
            AND completed_at IS NULL)
        OR (status = 'admitted' AND web_observation_request_id IS NOT NULL
            AND completed_at IS NULL)
        OR (status IN ('succeeded', 'unknown', 'cancelled')
            AND web_observation_request_id IS NOT NULL
            AND completed_at IS NOT NULL)
        OR (status = 'failed' AND completed_at IS NOT NULL)
    );
