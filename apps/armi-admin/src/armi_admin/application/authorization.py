"""Creator-signed, single-use authorization for an exact administrative preview."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid7

from armi_kernel.application import CredentialPurpose
from armi_local_control import environment_control_root
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_process import LocalProcessLock
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .configuration import AdminConfig
from .credentials import AdminCredentialPort
from .invocations import InvocationJournal


class AuthorizationError(ValueError):
    """An authorization error contains a code, never private preview content."""


class AuthorizationIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["armi.admin-authorization.v1"] = (
        "armi.admin-authorization.v1"
    )
    request_id: str
    environment_id: str
    incarnation: int = Field(ge=1)
    operator_id: str
    operation: str
    arguments: dict[str, JsonValue]
    preview: dict[str, JsonValue]
    expires_at: str

    def canonical(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical()).hexdigest()


class AuthorizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: AuthorizationIntent
    status: Literal["pending", "approved", "revoked", "consumed"] = "pending"
    signature: str | None = None
    issuer_id: str | None = None
    consumed_by: str | None = None


class AuthorizationStore:
    def __init__(self, config: AdminConfig, credentials: AdminCredentialPort) -> None:
        self.config = config
        self.credentials = credentials
        self.root = (
            environment_control_root(config.environment_root, config.environment_id)
            / "authorizations"
        )

    def _path(self, request_id: str) -> Path:
        from uuid import UUID

        try:
            parsed = UUID(request_id)
            if parsed.version != 7 or str(parsed) != request_id:
                raise ValueError
        except ValueError:
            raise AuthorizationError("ADMIN-AUTHORIZATION-ID") from None
        path = self.root / (request_id + ".json")
        if has_reparse_point(path, root=self.root.parent.parent.parent):
            raise AuthorizationError("ADMIN-AUTHORIZATION-PATH")
        return path

    def prepare(
        self,
        operation: str,
        arguments: dict[str, JsonValue],
        preview: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        if self.config.authorization_public_key is None:
            raise AuthorizationError("ADMIN-AUTHORIZATION-NOT-CONFIGURED")
        expires = min(
            datetime.now(UTC) + timedelta(minutes=10),
            datetime.fromisoformat(str(preview["expires_at"])),
        )
        intent = AuthorizationIntent(
            request_id=str(uuid7()),
            environment_id=self.config.environment_id,
            incarnation=self.config.environment_incarnation,
            operator_id=self.config.operator_id,
            operation=operation,
            arguments=arguments,
            preview=preview,
            expires_at=expires.isoformat(),
        )
        path = self._path(intent.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        InvocationJournal.save_record(
            path, AuthorizationRecord(intent=intent).model_dump(mode="json")
        )
        return {
            "request_id": intent.request_id,
            "request_digest": intent.digest,
            "intent": intent.model_dump(mode="json"),
        }

    def _read(self, request_id: str) -> AuthorizationRecord:
        path = self._path(request_id)
        if not path.is_file():
            raise AuthorizationError("ADMIN-AUTHORIZATION-NOT-FOUND")
        if path.stat().st_size > 4 * 1024 * 1024:
            raise AuthorizationError("ADMIN-AUTHORIZATION-SIZE")
        try:
            record = AuthorizationRecord.model_validate_json(path.read_bytes())
        except ValueError:
            raise AuthorizationError("ADMIN-AUTHORIZATION-INVALID") from None
        if (
            record.intent.request_id != request_id
            or record.intent.environment_id != self.config.environment_id
            or record.intent.incarnation != self.config.environment_incarnation
        ):
            raise AuthorizationError("ADMIN-AUTHORIZATION-ENVIRONMENT")
        return record

    def _require_recipient_or_issuer(self, record: AuthorizationRecord) -> None:
        if (
            record.intent.operator_id != self.config.operator_id
            and self.config.authorization_signing_key_locator is None
        ):
            raise AuthorizationError("ADMIN-AUTHORIZATION-OPERATOR")

    def get(self, request_id: str) -> dict[str, JsonValue]:
        record = self._read(request_id)
        self._require_recipient_or_issuer(record)
        return {
            **record.model_dump(mode="json", exclude={"signature"}),
            "request_digest": record.intent.digest,
            "expired": datetime.now(UTC)
            >= datetime.fromisoformat(record.intent.expires_at),
        }

    def approve(self, request_id: str, expected_digest: str) -> dict[str, JsonValue]:
        locator = self.config.authorization_signing_key_locator
        if (
            locator is None
            or "authorization_approve" not in self.config.authorized_operations
        ):
            raise AuthorizationError("ADMIN-AUTHORIZATION-ISSUER-REQUIRED")
        path = self._path(request_id)
        with LocalProcessLock(path.with_suffix(".lock")):
            record = self._read(request_id)
            if record.intent.digest != expected_digest:
                raise AuthorizationError("ADMIN-AUTHORIZATION-PREVIEW-CHANGED")
            if datetime.now(UTC) >= datetime.fromisoformat(record.intent.expires_at):
                raise AuthorizationError("ADMIN-AUTHORIZATION-EXPIRED")
            if record.status not in {"pending", "approved"}:
                raise AuthorizationError("ADMIN-AUTHORIZATION-NOT-PENDING")
            if record.status == "pending":

                def sign(secret: memoryview) -> bytes:
                    private = serialization.load_pem_private_key(
                        bytes(secret), password=None
                    )
                    if (
                        not isinstance(private, Ed25519PrivateKey)
                        or private.public_key().public_bytes_raw().hex()
                        != self.config.authorization_public_key
                    ):
                        raise AuthorizationError("ADMIN-AUTHORIZATION-KEY-MISMATCH")
                    return private.sign(record.intent.canonical())

                with self.credentials.resolve(
                    locator, CredentialPurpose("admin.authorization.sign")
                ) as handle:
                    record.signature = handle.consume(sign).hex()
                record.issuer_id = self.config.operator_id
                record.status = "approved"
                InvocationJournal.save_record(path, record.model_dump(mode="json"))
        return self.get(request_id)

    def revoke(self, request_id: str) -> dict[str, JsonValue]:
        path = self._path(request_id)
        with LocalProcessLock(path.with_suffix(".lock")):
            record = self._read(request_id)
            self._require_recipient_or_issuer(record)
            if record.status == "consumed":
                raise AuthorizationError("ADMIN-AUTHORIZATION-ALREADY-CONSUMED")
            record.status = "revoked"
            InvocationJournal.save_record(path, record.model_dump(mode="json"))
        return self.get(request_id)

    def consume(
        self,
        request_id: str,
        *,
        operation: str,
        arguments: dict[str, JsonValue],
        invocation_key: str,
    ) -> None:
        path = self._path(request_id)
        with LocalProcessLock(path.with_suffix(".lock")):
            record = self._read(request_id)
            intent = record.intent
            if (
                intent.operator_id != self.config.operator_id
                or intent.operation != operation
                or intent.arguments != arguments
            ):
                raise AuthorizationError("ADMIN-AUTHORIZATION-SCOPE")
            if record.status != "approved":
                raise AuthorizationError("ADMIN-AUTHORIZATION-NOT-APPROVED")
            if datetime.now(UTC) >= datetime.fromisoformat(intent.expires_at):
                raise AuthorizationError("ADMIN-AUTHORIZATION-EXPIRED")
            try:
                key = Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(self.config.authorization_public_key or "")
                )
                key.verify(bytes.fromhex(record.signature or ""), intent.canonical())
            except ValueError, InvalidSignature:
                raise AuthorizationError("ADMIN-AUTHORIZATION-SIGNATURE") from None
            record.status = "consumed"
            record.consumed_by = (
                "sha256:"
                + hashlib.sha256(
                    (
                        self.config.invocation_identity()
                        + "\0"
                        + operation
                        + "\0"
                        + invocation_key
                    ).encode()
                ).hexdigest()
            )
            InvocationJournal.save_record(path, record.model_dump(mode="json"))


__all__ = ("AuthorizationError", "AuthorizationIntent", "AuthorizationStore")
