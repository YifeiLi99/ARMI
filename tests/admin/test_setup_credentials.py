import json
from unittest.mock import Mock, patch

import pytest
from armi_admin.application.installation import SetupCredentialRequest, SetupError
from pydantic import SecretStr

from tests.admin.test_napcat_setup import application


@pytest.mark.parametrize(
    "name,value",
    [
        ("model.ark_api_key", "test-key"),
        (
            "speech.volc_credentials",
            "test-speech-key",
        ),
        ("codex.auth_json", '{"tokens":{}}'),
    ],
)
def test_provider_save_does_not_require_restart_or_claim_connection(
    tmp_path, name, value
):
    service = application(tmp_path / "environments/active")
    with patch.object(service, "_read", return_value=Mock(stage="ready")):
        result = service.credential(
            SetupCredentialRequest(name=name, action="put", value=SecretStr(value))
        )
    assert result["status"] == "configured"
    assert result["restart_required"] is False
    assert value not in json.dumps(result)


@pytest.mark.parametrize(
    "value", ['{"app_id":"app","access_token":"token"}', "key\r\ninjected", "   "]
)
def test_invalid_speech_key_does_not_overwrite_existing_secret(tmp_path, value):
    service = application(tmp_path / "environments/active")
    path = service.root / "secrets/provider-speech.volc_credentials"
    path.write_bytes(b"existing-private-value")
    with (
        patch.object(service, "_read", return_value=Mock(stage="ready")),
        pytest.raises(SetupError, match="FORMAT-INVALID"),
    ):
        service.credential(
            SetupCredentialRequest(
                name="speech.volc_credentials",
                action="put",
                value=SecretStr(value),
            )
        )
    assert path.read_bytes() == b"existing-private-value"


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_save_and_verify_returns_actual_result_without_hiding_saved_state(
    tmp_path, status
):
    service = application(tmp_path / "environments/active")
    verifier = Mock(
        return_value={"status": status, "checks": {"model": {"status": status}}}
    )
    service._verify_credential = verifier
    with patch.object(service, "_read", return_value=Mock(stage="ready")):
        result = service.credential(
            SetupCredentialRequest(
                name="model.ark_api_key",
                action="put_and_verify",
                value=SecretStr("test-key"),
            )
        )
    verifier.assert_called_once_with("model.ark_api_key", b"test-key")
    assert result["status"] == "configured"
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["status"] == status
    assert "test-key" not in json.dumps(result)


def test_verify_changed_secret_cannot_claim_success(tmp_path):
    service = application(tmp_path / "environments/active")
    path = service.root / "secrets/provider-model.ark_api_key"
    path.write_bytes(b"first")

    def verify(*args):
        path.write_bytes(b"second")
        return {"status": "passed"}

    service._verify_credential = verify
    with patch.object(service, "_read", return_value=Mock(stage="ready")):
        result = service.credential(
            SetupCredentialRequest(name="model.ark_api_key", action="verify")
        )
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["error_code"] == "SETUP-CREDENTIAL-CHANGED"
