"""T-07 preview token, atomic correction, and post-transaction side-work."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_artifact_store import ContentAddressedArtifactStore
from armi_kernel.application import ArtifactViolation, CredentialPurpose
from armi_kernel.contracts import Digest

from armi_admin.persistence import (
    AdminCorrectionGateway,
    AdminCorrectionGatewayError,
)

from .configuration import AdminConfig
from .control_plane import AdminControlPlane
from .credentials import AdminCredentialPort

_TOKEN_FIELDS = {
    "schema_version",
    "management_session_id",
    "environment_id",
    "incarnation",
    "purpose",
    "correction_kind",
    "command_digest",
    "subject_version",
    "state_epoch",
    "scope_digest",
    "impact_digest",
    "before_digest",
    "after_digest",
    "result_id",
    "side_work_id",
    "status_spec",
    "created_at",
    "expires_at",
    "nonce",
}


class AdminCorrectionError(RuntimeError):
    """A stable correction error without payloads, paths, or driver text."""


def _canonical(value: object) -> bytes:
    return rfc8785.dumps(cast(Any, value))


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decode_object(raw: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("object")
    return cast(dict[str, Any], value)


class AdminCorrectionCoordinator:
    """Coordinate the fixed S037 handlers without a general correction ledger."""

    __slots__ = ("_config", "_control", "_credentials")

    def __init__(
        self,
        config: AdminConfig,
        credentials: AdminCredentialPort,
        control: AdminControlPlane,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._control = control

    def preview(self, spec: dict[str, Any]) -> dict[str, Any]:
        result_id = str(uuid7())
        side_work_id = str(uuid7())
        snapshot = self._gateway().preview(
            spec,
            result_id=result_id,
            side_work_id=side_work_id,
        )
        now = datetime.now(UTC)
        payload = {
            "schema_version": "armi.admin-correction-preview.v1",
            "management_session_id": self._control.management_session_id,
            "environment_id": self._config.environment_id,
            "incarnation": self._config.environment_incarnation,
            "purpose": "admin.correction",
            "correction_kind": spec["correction_kind"],
            "command_digest": _digest(spec),
            "subject_version": snapshot["subject_version"],
            "state_epoch": snapshot["state_epoch"],
            "scope_digest": snapshot["scope_digest"],
            "impact_digest": snapshot["impact_digest"],
            "before_digest": snapshot["before_digest"],
            "after_digest": snapshot["after_digest"],
            "result_id": result_id,
            "side_work_id": side_work_id,
            "status_spec": snapshot["status_spec"],
            "created_at": _instant(now),
            "expires_at": _instant(now + timedelta(minutes=10)),
            "nonce": str(uuid7()),
        }
        return {
            "correction_kind": spec["correction_kind"],
            "target_count": snapshot["target_count"],
            "dependency_count": snapshot["dependency_count"],
            "side_work_required": snapshot["side_work_required"],
            "subject_version": snapshot["subject_version"],
            "state_epoch": snapshot["state_epoch"],
            "preview_token": self._encode(payload),
            "expires_at": payload["expires_at"],
        }

    def apply(self, spec: dict[str, Any], token: str) -> dict[str, Any]:
        payload = self._decode(token)
        if payload["management_session_id"] != self._control.management_session_id:
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-SESSION")
        if datetime.now(UTC) >= self._parse_time(payload["expires_at"]):
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-EXPIRED")
        self._validate_scope(payload)
        if payload["correction_kind"] != spec.get("correction_kind") or payload[
            "command_digest"
        ] != _digest(spec):
            raise AdminCorrectionError("ADMIN-CORRECTION-COMMAND-MISMATCH")
        self._control.ensure_runtime_stopped()
        try:
            return self._gateway().apply(spec, payload)
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(str(exc)) from None

    def status(self, token: str) -> dict[str, Any]:
        payload = self._decode(token)
        self._validate_scope(payload)
        try:
            return self._gateway().status(
                cast(dict[str, Any], payload["status_spec"]), payload
            )
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(str(exc)) from None

    def settle_side_work(self, side_work_id: str) -> dict[str, Any]:
        gateway = self._gateway()
        try:
            work = gateway.side_work(side_work_id)
            state = self._settle_artifact_file(work)
            settled = gateway.settle_side_work(
                side_work_id, str(work["content_digest"])
            )
            return {**settled, "file_result": state}
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(str(exc)) from None

    def _gateway(self) -> AdminCorrectionGateway:
        with self._credentials.resolve(
            self._config.locator, CredentialPurpose("database.admin")
        ) as handle:
            conninfo = handle.consume(lambda value: bytes(value).decode("utf-8"))
        return AdminCorrectionGateway(
            conninfo,
            expected_role=self._config.expected_role,
            environment_id=self._config.environment_id,
            incarnation=self._config.environment_incarnation,
        )

    def _encode(self, payload: dict[str, Any]) -> str:
        encoded = base64.urlsafe_b64encode(_canonical(payload)).rstrip(b"=")
        with self._credentials.resolve(
            self._config.preview_locator,
            CredentialPurpose("admin.correction.preview"),
        ) as handle:
            signature = handle.consume(
                lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
            )
        return (
            "correction-v1."
            + encoded.decode("ascii")
            + "."
            + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        )

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            prefix, payload_text, signature_text = token.split(".")
            if prefix != "correction-v1":
                raise ValueError("prefix")
            encoded = payload_text.encode("ascii")
            signature = base64.urlsafe_b64decode(
                signature_text + "=" * (-len(signature_text) % 4)
            )
            with self._credentials.resolve(
                self._config.preview_locator,
                CredentialPurpose("admin.correction.preview"),
            ) as handle:
                expected = handle.consume(
                    lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
                )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = _decode_object(
                base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
            )
            if set(payload) != _TOKEN_FIELDS:
                raise ValueError("fields")
            if (
                payload["schema_version"] != "armi.admin-correction-preview.v1"
                or payload["purpose"] != "admin.correction"
                or not isinstance(payload["status_spec"], dict)
            ):
                raise ValueError("contract")
            self._parse_time(payload["created_at"])
            self._parse_time(payload["expires_at"])
            return payload
        except AdminCorrectionError:
            raise
        except Exception as exc:
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-INVALID") from exc

    def _validate_scope(self, payload: dict[str, Any]) -> None:
        if (
            payload["environment_id"] != self._config.environment_id
            or payload["incarnation"] != self._config.environment_incarnation
        ):
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-SCOPE")

    @staticmethod
    def _parse_time(value: Any) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-TIME")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-TIME")
        return parsed.astimezone(UTC)

    def _settle_artifact_file(self, work: dict[str, Any]) -> str:
        artifact_root = self._config.environment_root / "data" / "artifacts"
        try:
            return ContentAddressedArtifactStore(
                artifact_root,
                max_object_bytes=104_857_600,
            ).settle_unregistered(Digest(str(work["content_digest"]))).value
        except (ArtifactViolation, ValueError):
            raise AdminCorrectionError("ADMIN-CORRECTION-ARTIFACT-FILE") from None


__all__ = ("AdminCorrectionCoordinator", "AdminCorrectionError")
