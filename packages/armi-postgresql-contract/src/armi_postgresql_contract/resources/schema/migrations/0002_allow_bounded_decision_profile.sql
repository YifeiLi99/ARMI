-- Finite Jev cognition uses a dedicated attempt profile, while the frozen
-- Context retains its original purpose. See DESIGN.md finite-judgment contract.
ALTER TABLE armi.cognitive_attempts
    DROP CONSTRAINT cognitive_attempts_profile_check,
    ADD CONSTRAINT cognitive_attempts_profile_check CHECK (
        profile = ANY (ARRAY[
            'autonomy_check'::text, 'creator_input_cognition'::text,
            'creator_cognitive_act'::text, 'creator_voice_act'::text,
            'creator_outreach'::text, 'other_human_dialogue'::text,
            'autonomous_activity'::text, 'activity_attention'::text,
            'activity_internal_work'::text, 'sleep_decision'::text,
            'memory_maintenance'::text, 'subject_self_check'::text,
            'reflect_self'::text, 'reflect_focus'::text, 'reflect_prompt'::text,
            'codex_task'::text, 'codex_result'::text, 'visual_observation'::text,
            'bounded_decision'::text
        ])
    );
