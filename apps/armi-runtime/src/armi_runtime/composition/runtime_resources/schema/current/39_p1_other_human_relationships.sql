ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.creator-dialogue-candidate.v11',
            'armi.creator-dialogue-candidate.v12',
            'armi.creator-dialogue-candidate.v13',
            'armi.creator-dialogue-candidate.v14',
            'armi.creator-dialogue-candidate.v15',
            'armi.creator-dialogue-candidate.v16',
            'armi.creator-dialogue-candidate.v17',
            'armi.creator-dialogue-candidate.v18',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1',
            'armi.maintenance-work-candidate.v1',
            'armi.other-human-dialogue-candidate.v1',
            'armi.other-human-dialogue-candidate.v2'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1', 'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3', 'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5', 'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v5',
            'armi.creator-dialogue-candidate.v6',
            'armi.creator-dialogue-candidate.v7',
            'armi.creator-dialogue-candidate.v8',
            'armi.creator-dialogue-candidate.v9',
            'armi.creator-dialogue-candidate.v10',
            'armi.creator-dialogue-candidate.v11',
            'armi.creator-dialogue-candidate.v12',
            'armi.creator-dialogue-candidate.v13',
            'armi.creator-dialogue-candidate.v14',
            'armi.creator-dialogue-candidate.v15',
            'armi.creator-dialogue-candidate.v16',
            'armi.creator-dialogue-candidate.v17',
            'armi.creator-dialogue-candidate.v18',
            'armi.autonomous-activity-candidate.v1',
            'armi.activity-attention-candidate.v1',
            'armi.activity-internal-work-candidate.v1',
            'armi.sleep-decision-candidate.v1',
            'armi.maintenance-work-candidate.v1',
            'armi.other-human-dialogue-candidate.v1',
            'armi.other-human-dialogue-candidate.v2'
        )
    );

ALTER TABLE armi.relationships
    DROP CONSTRAINT relationships_scope_check,
    ADD CONSTRAINT relationships_scope_check CHECK (
        scope IN ('creator_social', 'other_human_social')
    );

ALTER TABLE armi.other_human_dialogue_decisions
    DROP CONSTRAINT other_human_dialogue_decisions_check,
    ADD CONSTRAINT other_human_dialogue_decisions_check CHECK (
        (decision_kind = 'reply' AND subject_commit_id IS NOT NULL
            AND candidate_application_id IS NULL
            AND action_intent_id IS NOT NULL AND effect_id IS NOT NULL)
        OR (decision_kind = 'end_conversation' AND subject_commit_id IS NOT NULL
            AND candidate_application_id IS NULL
            AND action_intent_id IS NULL AND effect_id IS NULL)
        OR (decision_kind IN ('silence', 'defer')
            AND action_intent_id IS NULL AND effect_id IS NULL
            AND (
                (subject_commit_id IS NULL AND candidate_application_id IS NOT NULL)
                OR (subject_commit_id IS NOT NULL
                    AND candidate_application_id IS NULL)
            ))
    );
