"""Runtime-owned binding of the environment's identity matching key."""

from armi_runtime_foundation import PostgreSQLTransaction


class PostgreSQLEnvironmentIdentity:
    async def bind_identity_key(
        self, transaction: PostgreSQLTransaction, *, key_identity: str
    ) -> bool:
        # The environment owns this immutable binding; see DESIGN.md.
        row = await (
            await transaction.execute(
                """UPDATE armi.deployment_environments
                   SET identity_key_digest=COALESCE(identity_key_digest,%s),
                       identity_key_bound_at=COALESCE(identity_key_bound_at,statement_timestamp())
                   WHERE singleton_key AND (identity_key_digest IS NULL OR identity_key_digest=%s)
                   RETURNING identity_key_digest""",
                (key_identity, key_identity),
            )
        ).fetchone()
        return row is not None
