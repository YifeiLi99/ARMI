"""Online owner writes share Runtime's fences and commit their receipt atomically."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid7

from armi_artifact_store.api import ArtifactAdminContentPort
from armi_interaction.api import InteractionAdminPort
from armi_runtime_foundation import (
    AdminContentArtifactPort,
    AdminContentCommand,
    AdminContentContext,
    AdminContentGuardPort,
    AdminContentPort,
    AdminContentViolation,
    PostgreSQLAdminUnitOfWorkFactory,
)

from armi_admin.persistence.runtime_foundation import RuntimeFoundationAdminAdapter

from .configuration import AdminConfig
from .content_contracts import ContentWriteRequest


class ContentManagement:
    def __init__(
        self,
        config: AdminConfig,
        factory: PostgreSQLAdminUnitOfWorkFactory,
        *,
        owners: dict[str, AdminContentPort],
        guards: tuple[AdminContentGuardPort, ...],
        parties: InteractionAdminPort,
        artifacts: ArtifactAdminContentPort,
    ) -> None:
        self.config = config
        self.factory = factory
        self.owners = owners
        self.guards = guards
        self.parties = parties
        self.artifacts = artifacts
        self.runtime = RuntimeFoundationAdminAdapter(
            environment_id=config.environment_id,
            incarnation=config.environment_incarnation,
        )

    def write(self, request: ContentWriteRequest) -> dict[str, Any]:
        try:
            return self._write(request)
        except RuntimeError as error:
            code = getattr(error, "code", None)
            if isinstance(code, str):
                raise AdminContentViolation(code) from None
            raise

    def _write(self, request: ContentWriteRequest) -> dict[str, Any]:
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
        )
        receipt_arguments = dict(
            operator_id=self.config.operator_id,
            operation="content_write",
            key=request.idempotency_key,
            request_digest=digest,
        )
        with self.factory.repeatable_read() as unit:
            previous = self.runtime.read_admin_change(
                unit.transaction, **receipt_arguments
            )
            if previous is not None:
                return previous
        change = request.change
        owner = self.owners[change.owner]
        values = {} if change.data is None else change.data.model_dump(mode="json")
        for key in ("other_party_id", "material_kind"):
            if values.get(key) is None:
                values.pop(key, None)
        command = AdminContentCommand(
            change.action, UUID(change.object_id), change.expected_version, values
        )
        change_id = uuid7()
        publication = None
        if isinstance(owner, AdminContentArtifactPort):
            prepared = owner.prepare_content(command)
            if prepared is not None:
                body, kind, media = prepared
                publication = self.artifacts.prepare(
                    body, logical_kind=kind, media_type=media, change_id=change_id
                )
        with self.factory.serializable() as unit:
            tx = unit.transaction
            tx.execute("SET LOCAL lock_timeout = '100ms'")
            environment = self.runtime.environment(tx)
            if (
                environment is None
                or environment.environment_id != request.environment_id
                or environment.incarnation != self.config.environment_incarnation
            ):
                raise AdminContentViolation("ADMIN-ENVIRONMENT-MISMATCH")
            subject = self.runtime.content_guard(
                tx, generation_id=UUID(request.expected_generation_id)
            )
            previous = self.runtime.read_admin_change(tx, **receipt_arguments)
            if previous is not None:
                return previous
            if any(
                guard.content_busy(tx, subject_id=subject.subject_id)
                for guard in self.guards
            ):
                raise AdminContentViolation("ADMIN-CONTENT-BUSY")
            subject_party, creator_party = self.parties.content_parties(
                tx, subject_id=subject.subject_id
            )
            if change.owner == "relationship" and "other_party_id" in values:
                party_kind = self.parties.content_party_kind(
                    tx, party_id=UUID(values["other_party_id"])
                )
                if party_kind not in {"creator", "other_human"}:
                    raise AdminContentViolation("ADMIN-CONTENT-PARTY")
            if publication is not None:
                artifact = self.artifacts.register(
                    tx, artifact_id=uuid7(), publication=publication
                )
                command = replace(
                    command, values={**values, "_prepared_artifact": artifact}
                )
            result = owner.apply(
                tx,
                AdminContentContext(
                    subject.subject_id,
                    subject.generation_id,
                    change_id,
                    subject_party,
                    creator_party,
                ),
                command,
            )
            epoch = self.runtime.advance_state_epoch(
                tx, subject_id=subject.subject_id, expected=subject.state_epoch
            )
            if epoch is None:
                raise AdminContentViolation("ADMIN-CONTENT-VERSION-CONFLICT")
            instance = self.runtime.latest_runtime(tx)
            payload = {
                "admin_change_id": str(change_id),
                "execution_mode": "online",
                "owner": change.owner,
                "action": change.action,
                "generation_id": str(subject.generation_id),
                "state_epoch": epoch,
                "runtime_status": "not_started"
                if instance is None
                else str(instance[3]),
                "change": result,
            }
            self.runtime.record_admin_change(
                tx,
                change_id=change_id,
                **receipt_arguments,
                execution_mode="online",
                reason=request.reason,
                result=payload,
            )
            unit.commit()
            return payload


__all__ = ("ContentManagement",)
