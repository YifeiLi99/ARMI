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
            ) <> 5
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
        )
) AS checks(violation_code, violated)
WHERE violated
ORDER BY violation_code;
