ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_source_kind_check,
    DROP CONSTRAINT opportunities_source_shape_check,
    DROP CONSTRAINT opportunities_purpose_check,
    ADD CONSTRAINT opportunities_source_kind_check CHECK (
        source_kind IN (
            'external_evidence', 'life_generation_available',
            'subject_component_revision', 'activity_revision',
            'maintenance_window', 'maintenance_phase_revision',
            'life_material_revision', 'life_query_result',
            'creator_outreach_absence', 'creator_outreach_activity',
            'creator_outreach_relationship'
        )
    ),
    ADD CONSTRAINT opportunities_source_shape_check CHECK (
        (source_kind = 'external_evidence'
            AND evidence_id = source_ref AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind IN (
                'life_generation_available', 'subject_component_revision',
                'maintenance_window', 'maintenance_phase_revision',
                'life_material_revision'
            )
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NULL)
        OR (source_kind = 'activity_revision'
            AND evidence_id IS NULL AND scene_id IS NULL
            AND creator_party_id IS NULL AND activity_id IS NOT NULL)
        OR (source_kind = 'life_query_result'
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind IN (
                'creator_outreach_absence',
                'creator_outreach_relationship'
            )
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NULL)
        OR (source_kind = 'creator_outreach_activity'
            AND evidence_id IS NULL AND scene_id IS NOT NULL
            AND creator_party_id IS NOT NULL AND activity_id IS NOT NULL)
    ),
    ADD CONSTRAINT opportunities_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result', 'maintain_subjective_memory',
            'perform_subject_self_check', 'consider_creator_outreach'
        )
    );

ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_purpose_check,
    DROP CONSTRAINT cognitive_episodes_scene_shape_check,
    ADD CONSTRAINT cognitive_episodes_purpose_check CHECK (
        purpose IN (
            'consider_creator_input', 'consider_web_evidence',
            'consider_codex_task', 'consider_codex_result',
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'consider_life_query_result', 'maintain_subjective_memory',
            'perform_subject_self_check', 'consider_creator_outreach'
        )
    ),
    ADD CONSTRAINT cognitive_episodes_scene_shape_check CHECK (
        (purpose IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check'
        ) AND scene_id IS NULL AND creator_party_id IS NULL)
        OR (purpose NOT IN (
            'consider_autonomous_life', 'consider_activity_attention',
            'consider_activity_internal_work', 'consider_sleep',
            'maintain_subjective_memory', 'perform_subject_self_check'
        ) AND scene_id IS NOT NULL AND creator_party_id IS NOT NULL)
    );

ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile IN (
            'creator_input_cognition', 'creator_dialogue',
            'creator_outreach', 'autonomous_activity',
            'activity_attention', 'activity_internal_work',
            'sleep_decision', 'memory_maintenance', 'subject_self_check'
        )
    );
