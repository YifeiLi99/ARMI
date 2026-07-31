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
            ) <> 22
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
                      'cognitive_context_items'
                  )
            ) <> 2
        )
) AS checks(violation_code, violated)
WHERE violated
ORDER BY violation_code;
