"""T-07 preview token, atomic correction, and post-transaction side-work."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_kernel.application import CredentialPurpose

from armi_admin.persistence import (
    AdminCorrectionGateway,
    AdminCorrectionGatewayError,
)

from .configuration import AdminConfig
from .control_plane import AdminControlPlane
from .credentials import AdminCredentialPort, AdminSecretError

_TOKEN_FIELDS = {
    "schema_version",
    "management_session_id",
    "config_digest",
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

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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

    __slots__ = ("_config", "_control", "_credentials", "_gateway")

    def __init__(
        self,
        config: AdminConfig,
        credentials: AdminCredentialPort,
        control: AdminControlPlane,
        gateway: AdminCorrectionGateway,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._control = control
        self._gateway = gateway

    def preview(self, spec: dict[str, Any], *, purpose: str) -> dict[str, Any]:
        spec = self._owned_spec(spec, purpose=purpose)
        result_id = str(uuid7())
        side_work_id = str(uuid7())
        try:
            snapshot = self._gateway.preview(
                spec,
                result_id=result_id,
                side_work_id=side_work_id,
            )
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(exc.code) from None
        now = datetime.now(UTC)
        payload = {
            "schema_version": "armi.admin-correction-preview.v2",
            "management_session_id": self._control.management_session_id,
            "config_digest": self._config.safe_digest(),
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
        result = {
            "correction_kind": spec["correction_kind"],
            "target_count": snapshot["target_count"],
            "dependency_count": snapshot["dependency_count"],
            "side_work_required": snapshot["side_work_required"],
            "subject_version": snapshot["subject_version"],
            "state_epoch": snapshot["state_epoch"],
            "preview_token": self._encode(payload),
            "expires_at": payload["expires_at"],
            "target": spec,
            "impact": {
                "scope_digest": snapshot["scope_digest"],
                "impact_digest": snapshot["impact_digest"],
                "before_digest": snapshot["before_digest"],
                "after_digest": snapshot["after_digest"],
                "description": {
                    "replace_subject_component": "Replace the specified current subject component content through its owner.",
                    "repair_subject_component_head": "Point the specified component head at the reviewed historical version.",
                    "delete_uncommitted_creator_input": "Delete the specified uncommitted Creator input and settle dependent work.",
                    "requeue_stuck_work": "Requeue only the reviewed recoverable owner work.",
                    "reconcile_unknown_creator_effect": "Settle the unknown effect from the reviewed evidence without resending it.",
                }[spec["correction_kind"]],
            },
        }
        if snapshot.get("effect_reconciliation") is not None:
            result["effect_reconciliation"] = snapshot["effect_reconciliation"]
        return result

    def apply(
        self, spec: dict[str, Any], token: str, *, purpose: str
    ) -> dict[str, Any]:
        spec = self._owned_spec(spec, purpose=purpose)
        payload = self._decode(token)
        if payload.get("config_digest") != self._config.safe_digest():
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
            return self._gateway.apply(spec, payload)
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(exc.code) from None

    def _owned_spec(self, spec: dict[str, Any], *, purpose: str) -> dict[str, Any]:
        del purpose
        try:
            return self._gateway.canonicalize_spec(
                {
                    **spec,
                    "operator_purpose": "admin.correction",
                    "operator_identity": self._config.operator_id,
                }
            )
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(exc.code) from None

    def status(self, token: str) -> dict[str, Any]:
        payload = self._decode(token)
        self._validate_scope(payload)
        try:
            return self._gateway.status(
                cast(dict[str, Any], payload["status_spec"]), payload
            )
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(exc.code) from None

    def settle_side_work(self, side_work_id: str) -> dict[str, Any]:
        gateway = self._gateway
        try:
            work = gateway.side_work(side_work_id)
            return {
                "side_work_id": side_work_id,
                "status": work["status"],
                "file_result": "artifact_lifecycle_owned",
            }
        except AdminCorrectionGatewayError as exc:
            raise AdminCorrectionError(exc.code) from None

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
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-INVALID") from exc
        try:
            with self._credentials.resolve(
                self._config.preview_locator,
                CredentialPurpose("admin.correction.preview"),
            ) as handle:
                expected = handle.consume(
                    lambda key: hmac.new(bytes(key), encoded, hashlib.sha256).digest()
                )
        except AdminSecretError as exc:
            raise AdminCorrectionError("ADMIN-CORRECTION-PREVIEW-UNAVAILABLE") from exc
        try:
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            payload = _decode_object(
                base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
            )
            if set(payload) != _TOKEN_FIELDS:
                raise ValueError("fields")
            if (
                payload["schema_version"] != "armi.admin-correction-preview.v2"
                or payload["purpose"] != "admin.correction"
                or not isinstance(payload["status_spec"], dict)
            ):
                raise ValueError("contract")
            self._parse_time(payload["created_at"])
            self._parse_time(payload["expires_at"])
            return payload
        except AdminCorrectionError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
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


__all__ = ("AdminCorrectionCoordinator", "AdminCorrectionError")
