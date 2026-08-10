-- Add channel-neutral multi-party scenes and external identity bindings.

ALTER TABLE armi.parties
    DROP CONSTRAINT parties_display_label_check,
    DROP CONSTRAINT parties_party_kind_check,
    DROP CONSTRAINT parties_role_shape_check;
ALTER TABLE armi.parties
    ADD CONSTRAINT parties_display_label_check CHECK (
        (party_kind IN ('subject', 'creator') AND display_label IS NULL)
        OR (
            party_kind IN ('other_human', 'social_group')
            AND length(btrim(display_label)) BETWEEN 1 AND 256
        )
    ),
    ADD CONSTRAINT parties_party_kind_check CHECK (
        party_kind IN ('subject', 'creator', 'other_human', 'social_group')
    ),
    ADD CONSTRAINT parties_role_shape_check CHECK (
        (party_kind = 'subject' AND represented_subject_id IS NOT NULL
            AND creator_role IS NULL AND declared_identity_key IS NULL)
        OR (party_kind = 'creator' AND represented_subject_id IS NULL
            AND creator_role = 'unique_primary_creator'
            AND declared_identity_key IS NULL)
        OR (party_kind IN ('other_human', 'social_group')
            AND represented_subject_id IS NULL AND creator_role IS NULL
            AND declared_identity_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    );
CREATE UNIQUE INDEX parties_social_group_declared_identity_idx
    ON armi.parties (declared_identity_key)
    WHERE party_kind = 'social_group';

ALTER TABLE armi.interaction_scenes
    DROP CONSTRAINT interaction_scenes_audience_scope_check,
    DROP CONSTRAINT interaction_scenes_role_shape_check,
    DROP CONSTRAINT interaction_scenes_scene_kind_check;
ALTER TABLE armi.interaction_scenes
    ADD CONSTRAINT interaction_scenes_audience_scope_check CHECK (
        audience_scope IN ('creator', 'other_human', 'social_group')
    ),
    ADD CONSTRAINT interaction_scenes_role_shape_check CHECK (
        (scene_kind = 'creator_dialogue' AND audience_scope = 'creator'
            AND primary_party_kind = 'creator')
        OR (scene_kind = 'other_human_dialogue'
            AND audience_scope = 'other_human'
            AND primary_party_kind = 'other_human')
        OR (scene_kind = 'group_dialogue' AND audience_scope = 'social_group'
            AND primary_party_kind = 'social_group')
    ),
    ADD CONSTRAINT interaction_scenes_scene_kind_check CHECK (
        scene_kind IN ('creator_dialogue', 'other_human_dialogue', 'group_dialogue')
    ),
    ADD CONSTRAINT interaction_scenes_subject_identity_unique
        UNIQUE (scene_id, subject_id);

CREATE TABLE armi.scene_participants (
    scene_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    party_id uuid NOT NULL,
    participant_role text NOT NULL,
    first_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    last_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT scene_participants_pkey PRIMARY KEY (scene_id, party_id),
    CONSTRAINT scene_participants_identity_unique
        UNIQUE (scene_id, subject_id, party_id),
    CONSTRAINT scene_participants_role_check CHECK (
        participant_role IN ('primary', 'member')
    ),
    CONSTRAINT scene_participants_time_check CHECK (
        last_observed_at >= first_observed_at
    ),
    CONSTRAINT scene_participants_scene_fkey
        FOREIGN KEY (scene_id, subject_id)
        REFERENCES armi.interaction_scenes(scene_id, subject_id),
    CONSTRAINT scene_participants_party_fkey
        FOREIGN KEY (party_id) REFERENCES armi.parties(party_id)
);

INSERT INTO armi.scene_participants (
    scene_id, subject_id, party_id, participant_role, first_observed_at,
    last_observed_at
)
SELECT scene_id, subject_id, primary_party_id, 'primary', opened_at, opened_at
FROM armi.interaction_scenes;

ALTER TABLE armi.party_input_interactions
    DROP CONSTRAINT party_input_interactions_scene_owner_fkey,
    ADD CONSTRAINT party_input_interactions_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, source_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);
ALTER TABLE armi.action_intents
    DROP CONSTRAINT action_intents_scene_fkey,
    ADD CONSTRAINT action_intents_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, context_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);
ALTER TABLE armi.dialogue_decisions
    DROP CONSTRAINT dialogue_decisions_scene_owner_fkey,
    ADD CONSTRAINT dialogue_decisions_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, context_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);
ALTER TABLE armi.action_operations
    DROP CONSTRAINT action_operations_scene_owner_fkey,
    ADD CONSTRAINT action_operations_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, context_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);
ALTER TABLE armi.opportunities
    DROP CONSTRAINT opportunities_scene_owner_fkey,
    ADD CONSTRAINT opportunities_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, context_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);
ALTER TABLE armi.cognitive_episodes
    DROP CONSTRAINT cognitive_episodes_scene_owner_fkey,
    ADD CONSTRAINT cognitive_episodes_scene_participant_fkey
        FOREIGN KEY (scene_id, subject_id, context_party_id)
        REFERENCES armi.scene_participants(scene_id, subject_id, party_id);

CREATE TABLE armi.external_channel_bindings (
    external_binding_id uuid NOT NULL,
    channel_kind text NOT NULL,
    account_key text NOT NULL,
    external_kind text NOT NULL,
    external_key text NOT NULL,
    party_id uuid NOT NULL,
    party_kind text NOT NULL,
    scene_id uuid,
    display_label text NOT NULL,
    identity_assurance text NOT NULL,
    status text DEFAULT 'active' NOT NULL,
    first_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    last_observed_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT external_channel_bindings_pkey PRIMARY KEY (external_binding_id),
    CONSTRAINT external_channel_bindings_id_check CHECK (
        uuid_extract_version(external_binding_id) = 7
    ),
    CONSTRAINT external_channel_bindings_channel_check CHECK (
        channel_kind ~ '^[a-z][a-z0-9._-]{0,63}$'
    ),
    CONSTRAINT external_channel_bindings_account_check CHECK (
        account_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CONSTRAINT external_channel_bindings_external_key_check CHECK (
        external_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CONSTRAINT external_channel_bindings_kind_check CHECK (
        external_kind IN ('person', 'group')
    ),
    CONSTRAINT external_channel_bindings_shape_check CHECK (
        (external_kind = 'person' AND party_kind = 'other_human'
            AND scene_id IS NULL)
        OR (external_kind = 'group' AND party_kind = 'social_group'
            AND scene_id IS NOT NULL)
    ),
    CONSTRAINT external_channel_bindings_label_check CHECK (
        length(btrim(display_label)) BETWEEN 1 AND 256
    ),
    CONSTRAINT external_channel_bindings_assurance_check CHECK (
        identity_assurance = 'platform_observed'
    ),
    CONSTRAINT external_channel_bindings_status_check CHECK (status = 'active'),
    CONSTRAINT external_channel_bindings_time_check CHECK (
        last_observed_at >= first_observed_at
    ),
    CONSTRAINT external_channel_bindings_identity_unique
        UNIQUE (channel_kind, account_key, external_kind, external_key),
    CONSTRAINT external_channel_bindings_party_kind_fkey
        FOREIGN KEY (party_id, party_kind)
        REFERENCES armi.parties(party_id, party_kind),
    CONSTRAINT external_channel_bindings_scene_fkey
        FOREIGN KEY (scene_id) REFERENCES armi.interaction_scenes(scene_id)
);
CREATE UNIQUE INDEX external_channel_bindings_group_scene_idx
    ON armi.external_channel_bindings (scene_id)
    WHERE external_kind = 'group';
CREATE UNIQUE INDEX external_channel_bindings_person_party_idx
    ON armi.external_channel_bindings (channel_kind, account_key, party_id)
    WHERE external_kind = 'person';

ALTER TABLE armi.party_input_interactions
    ADD COLUMN external_binding_id uuid,
    ADD COLUMN external_message_key text,
    ADD COLUMN addressed_to_subject boolean,
    ADD CONSTRAINT party_input_interactions_external_shape_check CHECK (
        (external_binding_id IS NULL AND external_message_key IS NULL
            AND addressed_to_subject IS NULL)
        OR (purpose = 'other_human_message' AND external_binding_id IS NOT NULL
            AND external_message_key IS NOT NULL
            AND addressed_to_subject IS NOT NULL)
    ),
    ADD CONSTRAINT party_input_interactions_external_message_key_check CHECK (
        external_message_key IS NULL
        OR external_message_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    ADD CONSTRAINT party_input_interactions_external_binding_fkey
        FOREIGN KEY (external_binding_id)
        REFERENCES armi.external_channel_bindings(external_binding_id);
CREATE UNIQUE INDEX party_input_interactions_external_message_idx
    ON armi.party_input_interactions (external_binding_id, external_message_key)
    WHERE external_binding_id IS NOT NULL;

ALTER TABLE armi.capabilities
    DROP CONSTRAINT capabilities_kind_chk,
    DROP CONSTRAINT capabilities_operation_chk;
ALTER TABLE armi.capabilities
    ADD CONSTRAINT capabilities_kind_chk CHECK (
        capability_kind IN (
            'creator.scene.reply', 'codex.delegated-work',
            'local.other-human-inbox.deliver', 'external.group.message.send'
        )
    ),
    ADD CONSTRAINT capabilities_operation_chk CHECK (
        (capability_kind IN (
            'creator.scene.reply', 'local.other-human-inbox.deliver',
            'external.group.message.send'
        ) AND operation_class = 'send')
        OR (capability_kind = 'codex.delegated-work'
            AND operation_class = 'execute')
    );
INSERT INTO armi.capabilities (
    capability_id, capability_kind, adapter_kind, operation_class,
    scope_schema, availability_status, verification_capability,
    configuration_version, configuration_digest
) VALUES (
    '019feb70-0000-7000-8000-000000000001',
    'external.group.message.send', 'external-group', 'send',
    'armi.external-group-message-scope.v1', 'available',
    'platform_send_receipt_or_unknown', 1,
    'sha256:d8a9eb1f003f9d758f2e6c8a4308019d5c8e3c0bae0f65f517004bc5624bb655'
);

ALTER TABLE armi.action_intent_revisions
    DROP CONSTRAINT action_intent_revisions_family_check;
ALTER TABLE armi.action_intent_revisions
    ADD CONSTRAINT action_intent_revisions_family_check CHECK (
        (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL
            AND response_bytes IS NOT NULL AND media_type IS NOT NULL
            AND capability_kind = 'creator.scene.reply'
            AND operation_class = 'send' AND audience_scope = 'creator'
            AND data_scope = 'creator_visible_response'
            AND purpose = 'respond_to_creator'
            AND codex_task_source_id IS NULL AND task_manifest_digest IS NULL
            AND validator_id IS NULL)
        OR (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL
            AND response_bytes IS NOT NULL AND media_type IS NOT NULL
            AND capability_kind = 'local.other-human-inbox.deliver'
            AND operation_class = 'send' AND audience_scope = 'other_human'
            AND data_scope = 'declared_party_response'
            AND purpose = 'respond_to_other_human'
            AND codex_task_source_id IS NULL AND task_manifest_digest IS NULL
            AND validator_id IS NULL)
        OR (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL
            AND response_bytes IS NOT NULL AND media_type IS NOT NULL
            AND capability_kind = 'external.group.message.send'
            AND operation_class = 'send' AND audience_scope = 'social_group'
            AND data_scope = 'declared_party_response'
            AND purpose = 'respond_to_other_human'
            AND codex_task_source_id IS NULL AND task_manifest_digest IS NULL
            AND validator_id IS NULL)
        OR (response_artifact_id IS NULL AND response_digest IS NULL
            AND response_bytes IS NULL AND media_type IS NULL
            AND capability_kind = 'codex.delegated-work'
            AND operation_class = 'execute' AND audience_scope IS NULL
            AND data_scope IS NULL AND purpose = 'delegate_codex_work'
            AND codex_task_source_id IS NOT NULL
            AND task_manifest_digest IS NOT NULL
            AND task_manifest_digest ~ '^sha256:[0-9a-f]{64}$'
            AND validator_id IS NOT NULL)
    );

ALTER TABLE armi.effects
    ADD COLUMN destination_binding_id uuid,
    DROP CONSTRAINT effects_authorization_check,
    DROP CONSTRAINT effects_destination_check,
    DROP CONSTRAINT effects_family_check;
ALTER TABLE armi.effects
    ADD CONSTRAINT effects_authorization_check CHECK (
        authorization_basis IN (
            'creator_grant', 'runtime_builtin', 'runtime_configuration'
        )
    ),
    ADD CONSTRAINT effects_destination_check CHECK (
        destination_kind IN (
            'creator_inbox', 'other_human_inbox', 'codex_workspace',
            'external_group'
        )
    ),
    ADD CONSTRAINT effects_destination_binding_fkey
        FOREIGN KEY (destination_binding_id)
        REFERENCES armi.external_channel_bindings(external_binding_id),
    ADD CONSTRAINT effects_family_check CHECK (
        (effect_kind = 'creator_response'
            AND capability_kind = 'creator.scene.reply'
            AND operation_class = 'send' AND audience_scope = 'creator'
            AND data_scope = 'creator_visible_response'
            AND purpose = 'respond_to_creator'
            AND authorization_basis = 'creator_grant'
            AND destination_kind = 'creator_inbox'
            AND destination_party_id IS NOT NULL
            AND destination_binding_id IS NULL
            AND policy_decision_id IS NOT NULL)
        OR (effect_kind = 'local_inbox_delivery'
            AND capability_kind = 'local.other-human-inbox.deliver'
            AND operation_class = 'send' AND audience_scope = 'other_human'
            AND data_scope = 'declared_party_response'
            AND purpose = 'respond_to_other_human'
            AND authorization_basis = 'runtime_builtin'
            AND destination_kind = 'other_human_inbox'
            AND destination_party_id IS NOT NULL
            AND destination_binding_id IS NULL
            AND policy_decision_id IS NULL)
        OR (effect_kind = 'external_group_delivery'
            AND capability_kind = 'external.group.message.send'
            AND operation_class = 'send' AND audience_scope = 'social_group'
            AND data_scope = 'declared_party_response'
            AND purpose = 'respond_to_other_human'
            AND authorization_basis = 'runtime_configuration'
            AND destination_kind = 'external_group'
            AND destination_party_id IS NOT NULL
            AND destination_binding_id IS NOT NULL
            AND policy_decision_id IS NULL)
        OR (effect_kind = 'codex_delegation'
            AND capability_kind = 'codex.delegated-work'
            AND operation_class = 'execute' AND audience_scope IS NULL
            AND data_scope IS NULL AND purpose = 'delegate_codex_work'
            AND authorization_basis = 'creator_grant'
            AND destination_kind = 'codex_workspace'
            AND destination_party_id IS NOT NULL
            AND destination_binding_id IS NULL
            AND policy_decision_id IS NOT NULL)
    );

ALTER TABLE armi.effect_attempts
    DROP CONSTRAINT effect_attempts_adapter_binding_check;
ALTER TABLE armi.effect_attempts
    ADD CONSTRAINT effect_attempts_adapter_binding_check CHECK (
        adapter_binding IN (
            'armi.local-inbox-adapter.postgresql-v1',
            'armi.external-group-adapter.v1',
            'armi.codex-runner.openai-python-sdk-v1'
        )
    );

ALTER TABLE armi.effect_observations
    ADD COLUMN receiver_external_ref text,
    ADD CONSTRAINT effect_observations_external_ref_check CHECK (
        receiver_external_ref IS NULL
        OR receiver_external_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    ADD CONSTRAINT effect_observations_external_ref_shape_check CHECK (
        receiver_external_ref IS NULL OR observation_kind = 'receipt'
    );

ALTER TABLE armi.parties OWNER TO armi_owner;
ALTER TABLE armi.interaction_scenes OWNER TO armi_owner;
ALTER TABLE armi.scene_participants OWNER TO armi_owner;
ALTER TABLE armi.external_channel_bindings OWNER TO armi_owner;

REVOKE ALL ON TABLE armi.scene_participants FROM PUBLIC;
REVOKE ALL ON TABLE armi.external_channel_bindings FROM PUBLIC;
GRANT SELECT ON TABLE armi.scene_participants, armi.external_channel_bindings
    TO armi_admin;
GRANT INSERT, SELECT ON TABLE armi.scene_participants TO armi_runtime;
GRANT UPDATE (last_observed_at)
    ON TABLE armi.scene_participants TO armi_runtime;
GRANT INSERT, SELECT ON TABLE armi.external_channel_bindings TO armi_runtime;
GRANT UPDATE (display_label, last_observed_at)
    ON TABLE armi.external_channel_bindings TO armi_runtime;
GRANT UPDATE (display_label) ON TABLE armi.parties TO armi_runtime;
GRANT INSERT (receiver_external_ref)
    ON TABLE armi.effect_observations TO armi_admin, armi_runtime;
