import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest
from armi_admin.application import AdminConfig, AdminCredentialPort, AdminSecretError
from armi_admin.application.authorization import AuthorizationError, AuthorizationStore
from armi_kernel.application import CredentialPurpose
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@pytest.fixture
def stores(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    agent = AdminConfig.model_validate(
        {
            "schema_version": "armi.admin-config.v8",
            "operator_id": "delegated-agent",
            "authorized_operations": ("environment_reset", "authorization_get"),
            "environment_kind": "active",
            "environment_id": str(uuid7()),
            "environment_incarnation": 1,
            "environment_root": tmp_path / "environment",
            "resettable": False,
            "test_controls_enabled": False,
            "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
            "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
            "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
            "authorization_public_key": key.public_key().public_bytes_raw().hex(),
            "expected": {"package_set_digest": "sha256:" + "1" * 64},
        }
    )
    issuer = AdminConfig.model_validate(
        {
            **agent.model_dump(),
            "operator_id": "creator",
            "authorized_operations": (
                "authorization_approve",
                "authorization_get",
                "authorization_revoke",
            ),
            "authorization_signing_key_locator": "env:ARMI_SECRET_CREATOR_AUTHORIZATION_KEY",
        }
    )
    credentials = AdminCredentialPort(
        locator=agent.locator, config_root=tmp_path, environ={}
    )
    signer = AdminCredentialPort(
        locator=issuer.locator,
        config_root=tmp_path,
        authorization_locator=issuer.authorization_signing_key_locator,
        environ={
            "ARMI_SECRET_CREATOR_AUTHORIZATION_KEY": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
        },
    )
    return AuthorizationStore(agent, credentials), AuthorizationStore(issuer, signer)


def prepare(agent: AuthorizationStore):
    return agent.prepare(
        "environment_reset",
        {"preview_token": "exact-preview"},
        {
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            "target": "bound-environment",
            "subject_versions": {"mind": 4},
            "impact": "Delete the bound subject and generated artifacts.",
        },
    )


def test_separate_issuer_approves_exact_preview_and_grant_is_single_use(stores):
    agent, issuer = stores
    request = prepare(agent)
    rid, digest = request["request_id"], request["request_digest"]
    with pytest.raises(AuthorizationError, match="ISSUER-REQUIRED"):
        agent.approve(rid, digest)
    with pytest.raises(AdminSecretError, match="SCOPE"):
        agent.credentials.resolve(
            issuer.config.authorization_signing_key_locator,
            CredentialPurpose("admin.authorization.sign"),
        )
    with pytest.raises(AuthorizationError, match="PREVIEW-CHANGED"):
        issuer.approve(rid, "sha256:" + "0" * 64)
    issued = issuer.approve(rid, digest)
    assert issued["status"] == "approved"
    assert issued["intent"]["operator_id"] == "delegated-agent"
    agent.consume(
        rid,
        operation="environment_reset",
        arguments={"preview_token": "exact-preview"},
        invocation_key="first",
    )
    assert agent.get(rid)["status"] == "consumed"
    with pytest.raises(AuthorizationError, match="NOT-APPROVED"):
        agent.consume(
            rid,
            operation="environment_reset",
            arguments={"preview_token": "exact-preview"},
            invocation_key="second",
        )


def test_grant_rejects_changed_target_and_signed_content_tampering(stores):
    agent, issuer = stores
    request = prepare(agent)
    rid = str(request["request_id"])
    issuer.approve(rid, request["request_digest"])
    with pytest.raises(AuthorizationError, match="SCOPE"):
        agent.consume(
            rid,
            operation="environment_reset",
            arguments={"preview_token": "different"},
            invocation_key="first",
        )
    path = agent.root / (rid + ".json")
    record = json.loads(path.read_bytes())
    record["intent"]["arguments"]["preview_token"] = "different"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AuthorizationError, match="SIGNATURE"):
        agent.consume(
            rid,
            operation="environment_reset",
            arguments={"preview_token": "different"},
            invocation_key="first",
        )


def test_revoked_expired_and_other_operator_grants_cannot_execute(stores):
    agent, issuer = stores
    request = prepare(agent)
    rid = str(request["request_id"])
    issuer.approve(rid, request["request_digest"])
    issuer.revoke(rid)
    with pytest.raises(AuthorizationError, match="NOT-APPROVED"):
        agent.consume(
            rid,
            operation="environment_reset",
            arguments={"preview_token": "exact-preview"},
            invocation_key="first",
        )
    other = AuthorizationStore(
        agent.config.model_copy(update={"operator_id": "another-agent"}),
        agent.credentials,
    )
    with pytest.raises(AuthorizationError, match="OPERATOR"):
        other.get(rid)
    expired = agent.prepare(
        "environment_reset",
        {"preview_token": "expired"},
        {
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        },
    )
    with pytest.raises(AuthorizationError, match="EXPIRED"):
        issuer.approve(expired["request_id"], expired["request_digest"])
