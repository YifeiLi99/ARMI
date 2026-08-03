ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN ('creator_input_cognition', 'creator_dialogue')
    ),
    ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK (
        candidate_schema_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1'
        )
    );

ALTER TABLE armi.cognitive_candidate_validations
    DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check,
    ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK (
        candidate_contract_version IN (
            'armi.cognition-candidate.v1',
            'armi.cognition-candidate.v2',
            'armi.cognition-candidate.v3',
            'armi.cognition-candidate.v4',
            'armi.cognition-candidate.v5',
            'armi.cognition-candidate.v6',
            'armi.cognition-candidate.v7',
            'armi.creator-dialogue-candidate.v1'
        )
    );
