from uuid import UUID

from armi_runtime_foundation import PostgreSQLAdminTransaction


class PostgreSQLCodexAdmin:
    __slots__ = ()

    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int:
        del transaction, artifact_id
        # Codex tables are not readable by the current Admin role. Artifact
        # foreign keys remain the final CAS guard against catalog deletion.
        return 0


__all__ = ("PostgreSQLCodexAdmin",)
