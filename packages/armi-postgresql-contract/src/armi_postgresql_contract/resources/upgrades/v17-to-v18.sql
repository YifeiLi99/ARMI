ALTER TABLE armi.schema_baseline_identity DROP CONSTRAINT schema_baseline_identity_value_check;
ALTER TABLE armi.schema_baseline_identity ADD CONSTRAINT schema_baseline_identity_value_check CHECK (baseline_identity = 'armi.schema-baseline.v18'::text) NOT VALID;
UPDATE armi.schema_baseline_identity SET baseline_identity = 'armi.schema-baseline.v18';
ALTER TABLE armi.schema_baseline_identity VALIDATE CONSTRAINT schema_baseline_identity_value_check;

ALTER TABLE armi.cognitive_candidate_validations ADD COLUMN diagnostic_artifact_id uuid;
ALTER TABLE armi.dialogue_decisions DROP CONSTRAINT dialogue_decisions_kind_check;
ALTER TABLE armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_kind_check CHECK ((decision_kind = ANY (ARRAY['reply'::text, 'decline'::text, 'silence'::text, 'no_change'::text, 'need_information'::text, 'defer'::text, 'end_conversation'::text])));
ALTER TABLE armi.dialogue_decisions DROP CONSTRAINT dialogue_decisions_shape_check;
ALTER TABLE armi.dialogue_decisions ADD CONSTRAINT dialogue_decisions_shape_check CHECK ((((decision_kind <> 'end_conversation'::text) AND (proposal_ref IS NOT NULL) AND (action_intent_id IS NOT NULL)) OR ((decision_kind <> 'reply'::text) AND (action_intent_id IS NULL) AND (effect_id IS NULL))));
ALTER TABLE armi.cognitive_candidate_validations ADD CONSTRAINT cognitive_candidate_validations_diagnostic_artifact_id_fkey FOREIGN KEY (diagnostic_artifact_id) REFERENCES armi.artifacts(artifact_id);

CREATE TABLE armi.system_notifications (
    notification_id uuid NOT NULL PRIMARY KEY,
    interaction_id uuid NOT NULL UNIQUE,
    operation_id uuid,
    subject_id uuid NOT NULL,
    scene_id uuid NOT NULL,
    destination_party_id uuid NOT NULL,
    category text NOT NULL CHECK (category = 'technical_failure'),
    failure_code text NOT NULL CHECK (failure_code ~ '^[A-Z][A-Z0-9_-]{0,127}$'),
    send_unknown boolean NOT NULL,
    payload_artifact_id uuid NOT NULL,
    delivery_status text NOT NULL CHECK (delivery_status IN ('registered','unavailable')),
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    registered_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    UNIQUE (operation_id, category),
    UNIQUE (notification_id, subject_id, scene_id),
    CHECK (uuid_extract_version(notification_id) = 7)
);
ALTER TABLE armi.effects ALTER COLUMN action_intent_revision_id DROP NOT NULL;
ALTER TABLE armi.effects ALTER COLUMN action_intent_id DROP NOT NULL;
ALTER TABLE armi.effects ADD COLUMN system_notification_id uuid UNIQUE;
ALTER TABLE armi.effects ADD CONSTRAINT effects_origin_check CHECK ((system_notification_id IS NOT NULL AND action_intent_id IS NULL AND action_intent_revision_id IS NULL) OR (system_notification_id IS NULL AND action_intent_id IS NOT NULL AND action_intent_revision_id IS NOT NULL));
ALTER TABLE armi.effects DROP CONSTRAINT effects_family_check;
ALTER TABLE armi.effects ADD CONSTRAINT effects_family_check CHECK ((system_notification_id IS NOT NULL AND effect_kind='system_notification' AND capability_kind='interaction.system.notify' AND operation_class='send' AND audience_scope='original_sender' AND data_scope='system_notification' AND purpose='notify_technical_failure' AND destination_kind IN ('creator_inbox','other_human_inbox','external_group','external_private') AND destination_party_id IS NOT NULL AND ((destination_kind IN ('creator_inbox','other_human_inbox') AND destination_binding_id IS NULL AND authorization_basis='runtime_builtin') OR (destination_kind IN ('external_group','external_private') AND destination_binding_id IS NOT NULL AND authorization_basis='runtime_configuration'))) OR (system_notification_id IS NULL AND (((effect_kind = 'creator_response'::text) AND (capability_kind = 'creator.scene.reply'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'creator'::text) AND (data_scope = 'creator_visible_response'::text) AND (purpose = 'respond_to_creator'::text) AND (authorization_basis = CASE WHEN destination_kind = 'creator_inbox' THEN 'runtime_builtin' ELSE 'runtime_configuration' END) AND (destination_kind = ANY (ARRAY['creator_inbox'::text, 'external_private'::text, 'live_voice_audio'::text])) AND (destination_party_id IS NOT NULL) AND (((destination_kind = ANY (ARRAY['creator_inbox'::text, 'live_voice_audio'::text])) AND (destination_binding_id IS NULL)) OR ((destination_kind = 'external_private'::text) AND (destination_binding_id IS NOT NULL)))) OR ((effect_kind = 'local_inbox_delivery'::text) AND (capability_kind = 'local.other-human-inbox.deliver'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_builtin'::text) AND (destination_kind = 'other_human_inbox'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NULL)) OR ((effect_kind = 'external_group_delivery'::text) AND (capability_kind = 'external.group.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'social_group'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_configuration'::text) AND (destination_kind = 'external_group'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NOT NULL)) OR ((effect_kind = 'external_private_delivery'::text) AND (capability_kind = 'external.private.message.send'::text) AND (operation_class = 'send'::text) AND (audience_scope = 'other_human'::text) AND (data_scope = 'declared_party_response'::text) AND (purpose = 'respond_to_other_human'::text) AND (authorization_basis = 'runtime_configuration'::text) AND (destination_kind = 'external_private'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NOT NULL)) OR ((effect_kind = 'codex_delegation'::text) AND (capability_kind = 'codex.delegated-work'::text) AND (operation_class = 'execute'::text) AND (audience_scope IS NULL) AND (data_scope IS NULL) AND (purpose = 'delegate_codex_work'::text) AND (authorization_basis = 'runtime_configuration'::text) AND (destination_kind = 'codex_workspace'::text) AND (destination_party_id IS NOT NULL) AND (destination_binding_id IS NULL)))));
ALTER TABLE ONLY armi.system_notifications
    ADD CONSTRAINT system_notifications_input_fkey FOREIGN KEY (interaction_id) REFERENCES armi.party_input_interactions(interaction_id),
    ADD CONSTRAINT system_notifications_operation_fkey FOREIGN KEY (operation_id) REFERENCES armi.opportunities(opportunity_id),
    ADD CONSTRAINT system_notifications_subject_fkey FOREIGN KEY (subject_id) REFERENCES armi.subjects(subject_id),
    ADD CONSTRAINT system_notifications_scene_fkey FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id),
    ADD CONSTRAINT system_notifications_party_fkey FOREIGN KEY (destination_party_id) REFERENCES armi.parties(party_id),
    ADD CONSTRAINT system_notifications_artifact_fkey FOREIGN KEY (payload_artifact_id) REFERENCES armi.artifacts(artifact_id);
ALTER TABLE ONLY armi.effects
    ADD CONSTRAINT effects_system_notification_fkey FOREIGN KEY (system_notification_id,subject_id,scene_id) REFERENCES armi.system_notifications(notification_id,subject_id,scene_id);
GRANT SELECT ON TABLE armi.system_notifications TO armi_admin;
GRANT SELECT, INSERT ON TABLE armi.system_notifications TO armi_runtime;

ALTER TABLE armi.cognitive_attempts DROP CONSTRAINT cognitive_attempts_candidate_schema_version_check;
ALTER TABLE armi.cognitive_attempts ADD CONSTRAINT cognitive_attempts_candidate_schema_version_check CHECK ((candidate_schema_version = ANY (ARRAY['armi.cognition-candidate.v12'::text, 'armi.creator-dialogue-candidate.v25'::text, 'armi.creator-cognitive-act-candidate.v3'::text, 'armi.creator-voice-act-candidate.v3'::text, 'armi.autonomous-activity-candidate.v4'::text, 'armi.activity-attention-candidate.v4'::text, 'armi.activity-internal-work-candidate.v3'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.owner-reflection-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v6'::text, 'armi.visual-observation-candidate.v1'::text, 'armi.creator-cognitive-act-candidate.v4'::text, 'armi.creator-voice-act-candidate.v4'::text, 'armi.cognition-candidate.v13'::text, 'armi.activity-attention-candidate.v5'::text, 'armi.activity-internal-work-candidate.v4'::text, 'armi.autonomous-activity-candidate.v5'::text, 'armi.other-human-dialogue-candidate.v7'::text, 'armi.visual-observation-candidate.v2'::text, 'armi.owner-reflection-candidate.v2'::text, 'armi.maintenance-work-candidate.v2'::text])));
ALTER TABLE armi.cognitive_candidate_validations DROP CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check;
ALTER TABLE armi.cognitive_candidate_validations ADD CONSTRAINT cognitive_candidate_validation_candidate_contract_version_check CHECK ((candidate_contract_version = ANY (ARRAY['armi.cognition-candidate.v12'::text, 'armi.creator-dialogue-candidate.v25'::text, 'armi.creator-cognitive-act-candidate.v3'::text, 'armi.creator-voice-act-candidate.v3'::text, 'armi.autonomous-activity-candidate.v4'::text, 'armi.activity-attention-candidate.v4'::text, 'armi.activity-internal-work-candidate.v3'::text, 'armi.sleep-decision-candidate.v1'::text, 'armi.maintenance-work-candidate.v1'::text, 'armi.owner-reflection-candidate.v1'::text, 'armi.other-human-dialogue-candidate.v6'::text, 'armi.visual-observation-candidate.v1'::text, 'armi.creator-cognitive-act-candidate.v4'::text, 'armi.creator-voice-act-candidate.v4'::text, 'armi.cognition-candidate.v13'::text, 'armi.activity-attention-candidate.v5'::text, 'armi.activity-internal-work-candidate.v4'::text, 'armi.autonomous-activity-candidate.v5'::text, 'armi.other-human-dialogue-candidate.v7'::text, 'armi.visual-observation-candidate.v2'::text, 'armi.owner-reflection-candidate.v2'::text, 'armi.maintenance-work-candidate.v2'::text])));
