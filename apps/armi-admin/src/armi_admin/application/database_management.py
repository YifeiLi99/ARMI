"""Database administration with a transactional receipt and explicit maintenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid7

from armi_runtime_foundation import PostgreSQLAdminUnitOfWorkFactory

from armi_admin.persistence.database_tables import (
    DatabaseTableError,
    change_table,
    query_table,
    table_catalog,
)
from armi_admin.persistence.runtime_foundation import RuntimeFoundationAdminAdapter

from .configuration import AdminConfig
from .database_contracts import (
    DatabaseBatchRequest,
    DatabaseCatalogRequest,
    DatabaseQueryRequest,
)


class DatabaseManagement:
    def __init__(
        self, config: AdminConfig, factory: PostgreSQLAdminUnitOfWorkFactory
    ) -> None:
        self.config = config
        self.factory = factory
        self.runtime = RuntimeFoundationAdminAdapter(
            environment_id=config.environment_id,
            incarnation=config.environment_incarnation,
        )

    def read(
        self, request: DatabaseCatalogRequest | DatabaseQueryRequest
    ) -> dict[str, Any]:
        with self.factory.repeatable_read() as uow:
            environment = self.runtime.environment(uow.transaction)
            if (
                environment is None
                or environment.environment_id != self.config.environment_id
                or environment.incarnation != self.config.environment_incarnation
            ):
                raise DatabaseTableError("ADMIN-ENVIRONMENT-MISMATCH")
            catalog = table_catalog(uow.transaction)
            if request.table is not None and request.table not in catalog:
                raise DatabaseTableError("ADMIN-DATABASE-TABLE")
            if isinstance(request, DatabaseQueryRequest):
                return query_table(uow.transaction, catalog[request.table], request)
            return {
                "tables": [
                    table.describe()
                    for name, table in catalog.items()
                    if request.table is None or name == request.table
                ],
                "execution_mode": "read_only",
            }

    def mutate(self, request: DatabaseBatchRequest) -> dict[str, Any]:
        """Caller holds the environment control lock with business processes stopped."""
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                ).encode()
            ).hexdigest()
        )
        with self.factory.serializable() as uow:
            tx = uow.transaction
            self.runtime.authority_lock(tx)
            environment = self.runtime.environment(tx)
            if (
                environment is None
                or environment.environment_id != self.config.environment_id
                or environment.incarnation != self.config.environment_incarnation
            ):
                raise DatabaseTableError("ADMIN-ENVIRONMENT-MISMATCH")
            previous = self.runtime.read_admin_change(
                tx,
                operator_id=self.config.operator_id,
                operation="database_batch",
                key=request.idempotency_key,
                request_digest=digest,
            )
            if previous is not None:
                return previous
            if not self.runtime.fence_expired_authority(tx):
                raise DatabaseTableError("ADMIN-DATABASE-RUNTIME-BUSY")
            catalog = table_catalog(tx)
            # Validate every policy before the first DML; constraints remain PostgreSQL's responsibility.
            for change in request.changes:
                if change.table not in catalog:
                    raise DatabaseTableError("ADMIN-DATABASE-TABLE")
                if not catalog[change.table].writable:
                    raise DatabaseTableError("ADMIN-DATABASE-READ-ONLY")
            changes: list[dict[str, Any]] = []
            for change in request.changes:
                table = catalog[change.table]
                result = change_table(tx, table, change)
                changes.append(
                    {
                        "table": table.name,
                        "action": change.action,
                        "affected_count": result["affected_count"],
                        "key": {
                            field: result["values"][field]
                            for field in table.primary_key
                        },
                        "new_version": None
                        if change.action == "delete"
                        else result["version"],
                        "history_retention": "physical_table_operation",
                    }
                )
            change_id = uuid7()
            payload = {
                "admin_change_id": str(change_id),
                "execution_mode": "maintenance",
                "runtime_status": "stopped",
                "changes": changes,
            }
            self.runtime.record_admin_change(
                tx,
                change_id=change_id,
                operator_id=self.config.operator_id,
                operation="database_batch",
                key=request.idempotency_key,
                request_digest=digest,
                execution_mode="maintenance",
                reason=request.reason,
                result=payload,
            )
            uow.commit()
            return payload

    def reconcile(
        self, *, operation: str, key: str, request_digest: str
    ) -> dict[str, Any] | None:
        with self.factory.repeatable_read() as uow:
            return self.runtime.read_admin_change(
                uow.transaction,
                operator_id=self.config.operator_id,
                operation=operation,
                key=key,
                request_digest=request_digest,
            )


__all__ = ("DatabaseManagement",)
