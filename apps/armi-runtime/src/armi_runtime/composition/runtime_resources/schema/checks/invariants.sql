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
            ) <> 50
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
        )
) AS checks(violation_code, violated)
WHERE violated
ORDER BY violation_code;
