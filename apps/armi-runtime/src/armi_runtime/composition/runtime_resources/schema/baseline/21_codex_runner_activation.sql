UPDATE armi.capabilities
SET availability_status = 'available',
    verification_capability = 'codex_runner_openai_python_sdk_isolation_v2',
    configuration_version = 2,
    configuration_digest = 'sha256:784efc4ae76060da99d37fd2aaa2872e105ade73a46dee212f4660c4707c1d87'
WHERE capability_kind = 'codex.delegated-work'
  AND operation_class = 'execute'
  AND scope_schema = 'armi.codex-delegated-work-scope.v1'
  AND availability_status = 'unavailable'
  AND verification_capability = 'runner_not_implemented'
  AND configuration_version = 1;

DO $armi_codex_catalog$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM armi.capabilities
        WHERE capability_kind = 'codex.delegated-work'
          AND operation_class = 'execute'
          AND availability_status = 'available'
          AND verification_capability = 'codex_runner_openai_python_sdk_isolation_v2'
          AND configuration_version = 2
          AND configuration_digest = 'sha256:784efc4ae76060da99d37fd2aaa2872e105ade73a46dee212f4660c4707c1d87'
    ) THEN
        RAISE EXCEPTION 'codex capability catalog activation precondition failed'
            USING ERRCODE = '23514';
    END IF;
END
$armi_codex_catalog$;

ALTER TABLE armi.permission_grants
    ALTER COLUMN audience_scope DROP NOT NULL,
    ALTER COLUMN data_scope DROP NOT NULL,
    ALTER COLUMN max_payload_bytes DROP NOT NULL,
    ADD COLUMN workspace_scope text,
    ADD COLUMN artifact_scope text,
    ADD COLUMN network_access boolean,
    DROP CONSTRAINT permission_grants_scope_chk,
    ADD CONSTRAINT permission_grants_scope_chk CHECK (
        (
            operation_class = 'send'
            AND audience_scope = 'creator'
            AND data_scope = 'creator_visible_response'
            AND purpose = 'respond_to_creator'
            AND workspace_scope IS NULL
            AND artifact_scope IS NULL
            AND network_access IS NULL
            AND valid_until > valid_from
            AND valid_until <= valid_from + interval '7 days'
            AND max_uses BETWEEN 1 AND 16
            AND consumed_uses BETWEEN 0 AND max_uses
            AND max_payload_bytes BETWEEN 1 AND 65536
        )
        OR
        (
            operation_class = 'execute'
            AND audience_scope IS NULL
            AND data_scope IS NULL
            AND purpose = 'delegate_codex_work'
            AND workspace_scope = 'isolated_ephemeral'
            AND artifact_scope = 'explicit_only'
            AND network_access = false
            AND valid_until > valid_from
            AND valid_until <= valid_from + interval '1 hour'
            AND max_uses = 1
            AND consumed_uses BETWEEN 0 AND 1
            AND max_payload_bytes IS NULL
        )
    );

GRANT INSERT (workspace_scope, artifact_scope, network_access)
ON armi.permission_grants TO armi_runtime;
