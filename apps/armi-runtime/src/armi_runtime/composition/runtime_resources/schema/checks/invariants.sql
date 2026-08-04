SELECT violation_code
FROM (
    VALUES
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_namespace
                WHERE nspname = 'armi'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'schema_migrations'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-DIRTY',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            ) <> 57
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'artifacts'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'audit_events'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'durable_work'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'outbox_items'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'subjects',
                      'life_generations',
                      'runtime_bundle_activations',
                      'parties',
                      'prompt_documents',
                      'prompt_revisions',
                      'subject_component_heads',
                      'subject_component_revisions'
                  )
            ) <> 8
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'runtime_instances'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'runtime_recovery_runs'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'interaction_scenes',
                      'scene_timeline_items'
                  )
            ) <> 2
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'creator_input_interactions',
                      'external_evidence',
                      'opportunities'
                  )
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'activities',
                      'activity_revisions'
                  )
            ) <> 2
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'codex_task_sources',
                      'codex_verification_results',
                      'codex_result_sources'
                  )
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'cognitive_episodes',
                      'cognitive_context_items',
                      'cognitive_attempts',
                      'cognitive_candidate_validations',
                      'cognitive_candidate_validation_items',
                      'cognitive_candidate_basis_links'
                  )
            ) <> 6
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'subject_commits',
                      'accepted_experiences',
                      'experience_evidence_links',
                      'cognitive_candidate_applications'
                  )
            ) <> 4
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'capabilities',
                      'capability_requests',
                      'capability_request_basis_links',
                      'capability_request_decisions',
                      'permission_grants'
                  )
            ) <> 5
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'action_intents',
                      'action_intent_revisions',
                      'formal_no_action_decisions',
                      'creator_response_operations'
                  )
            ) <> 4
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'policy_decisions',
                      'effects',
                      'effect_outbox_items'
                  )
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'creator_response_deliveries',
                      'effect_attempts',
                      'effect_observations'
                  )
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'web_observation_requests',
                      'observation_attempts',
                      'observation_tool_calls'
                  )
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind = 'r'
                  AND relation.relname IN (
                      'web_research_intents',
                      'web_evidence_sources'
                  )
            ) <> 2
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'deployment_environments'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'runtime_recovery_runs'
                  AND attribute.attname = 'resumable_admin_correction_work_count'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'permission_grants'
                  AND attribute.attname IN (
                      'workspace_scope',
                      'artifact_scope',
                      'network_access'
                  )
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'runtime_recovery_runs'
                  AND attribute.attname IN (
                      'resumable_codex_task_count',
                      'resumable_codex_effect_count',
                      'pending_codex_result_acceptance_count'
                  )
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ) <> 3
        ),
        (
            'DB-SCHEMA-MISSING',
            NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'activity_attention_decisions'
                  AND relation.relkind = 'r'
            )
        ),
        (
            'DB-SCHEMA-MISSING',
            (
                SELECT count(*)
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = 'activity_revisions'
                  AND attribute.attname IN (
                      'transition_kind',
                      'waiting_condition_kind',
                      'resume_not_before'
                  )
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
            ) <> 3
        )
) AS checks(violation_code, violated)
WHERE violated
ORDER BY violation_code;
