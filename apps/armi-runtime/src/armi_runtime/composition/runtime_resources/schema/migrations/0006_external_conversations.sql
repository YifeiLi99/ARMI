-- Unify direct and group external conversations without changing existing data.

ALTER TABLE armi.external_channel_bindings
    DROP CONSTRAINT external_channel_bindings_shape_check,
    DROP CONSTRAINT external_channel_bindings_assurance_check;
ALTER TABLE armi.external_channel_bindings
    ADD CONSTRAINT external_channel_bindings_shape_check CHECK (
        (external_kind = 'person' AND party_kind = 'creator'
            AND scene_id IS NOT NULL
            AND identity_assurance = 'runtime_configuration')
        OR (external_kind = 'person' AND party_kind = 'other_human'
            AND identity_assurance = 'platform_observed')
        OR (external_kind = 'group' AND party_kind = 'social_group'
            AND scene_id IS NOT NULL
            AND identity_assurance = 'platform_observed')
    ),
    ADD CONSTRAINT external_channel_bindings_assurance_check CHECK (
        identity_assurance IN ('platform_observed', 'runtime_configuration')
    );

ALTER TABLE armi.party_input_interactions
    DROP CONSTRAINT party_input_interactions_external_shape_check;
ALTER TABLE armi.party_input_interactions
    ADD CONSTRAINT party_input_interactions_external_shape_check CHECK (
        (external_binding_id IS NULL AND external_message_key IS NULL
            AND addressed_to_subject IS NULL)
        OR (purpose IN ('creator_message', 'other_human_message')
            AND external_binding_id IS NOT NULL
            AND external_message_key IS NOT NULL
            AND addressed_to_subject IS NOT NULL)
    );

ALTER TABLE armi.capabilities
    DROP CONSTRAINT capabilities_kind_chk,
    DROP CONSTRAINT capabilities_operation_chk;
ALTER TABLE armi.capabilities
    ADD CONSTRAINT capabilities_kind_chk CHECK (
        capability_kind IN (
            'creator.scene.reply', 'codex.delegated-work',
            'local.other-human-inbox.deliver', 'external.group.message.send',
            'external.private.message.send'
        )
    ),
    ADD CONSTRAINT capabilities_operation_chk CHECK (
        (capability_kind IN (
            'creator.scene.reply', 'local.other-human-inbox.deliver',
            'external.group.message.send', 'external.private.message.send'
        ) AND operation_class = 'send')
        OR (capability_kind = 'codex.delegated-work'
            AND operation_class = 'execute')
    );
INSERT INTO armi.capabilities (
    capability_id, capability_kind, adapter_kind, operation_class,
    scope_schema, availability_status, verification_capability,
    configuration_version
) VALUES (
    '019feef5-0006-7000-8000-000000000001',
    'external.private.message.send', 'external-message', 'send',
    'armi.external-private-message-scope.v1', 'available',
    'platform_send_receipt_or_unknown', 1
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
        OR (response_artifact_id IS NOT NULL AND response_digest IS NOT NULL
            AND response_bytes IS NOT NULL AND media_type IS NOT NULL
            AND capability_kind = 'external.private.message.send'
            AND operation_class = 'send' AND audience_scope = 'other_human'
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
    DROP CONSTRAINT effects_destination_check,
    DROP CONSTRAINT effects_family_check;
ALTER TABLE armi.effects
    ADD CONSTRAINT effects_destination_check CHECK (
        destination_kind IN (
            'creator_inbox', 'other_human_inbox', 'codex_workspace',
            'external_group', 'external_private'
        )
    ),
    ADD CONSTRAINT effects_family_check CHECK (
        (effect_kind = 'creator_response'
            AND capability_kind = 'creator.scene.reply'
            AND operation_class = 'send' AND audience_scope = 'creator'
            AND data_scope = 'creator_visible_response'
            AND purpose = 'respond_to_creator'
            AND authorization_basis = 'creator_grant'
            AND destination_kind IN ('creator_inbox', 'external_private')
            AND destination_party_id IS NOT NULL
            AND ((destination_kind = 'creator_inbox'
                    AND destination_binding_id IS NULL)
                OR (destination_kind = 'external_private'
                    AND destination_binding_id IS NOT NULL))
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
        OR (effect_kind = 'external_private_delivery'
            AND capability_kind = 'external.private.message.send'
            AND operation_class = 'send' AND audience_scope = 'other_human'
            AND data_scope = 'declared_party_response'
            AND purpose = 'respond_to_other_human'
            AND authorization_basis = 'runtime_configuration'
            AND destination_kind = 'external_private'
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

UPDATE armi.effect_attempts
SET adapter_binding = 'armi.external-message-adapter.v1'
WHERE adapter_binding = 'armi.external-group-adapter.v1';
ALTER TABLE armi.effect_attempts
    DROP CONSTRAINT effect_attempts_adapter_binding_check;
ALTER TABLE armi.effect_attempts
    ADD CONSTRAINT effect_attempts_adapter_binding_check CHECK (
        adapter_binding IN (
            'armi.local-inbox-adapter.postgresql-v1',
            'armi.external-message-adapter.v1',
            'armi.codex-runner.openai-python-sdk-v1'
        )
    );

GRANT UPDATE (scene_id, display_label, last_observed_at)
    ON TABLE armi.external_channel_bindings TO armi_runtime;
