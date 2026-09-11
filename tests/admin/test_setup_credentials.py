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
            '{"app_id":"test-app","access_token":"test-token"}',
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


def test_invalid_speech_document_does_not_overwrite_existing_secret(tmp_path):
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
                value=SecretStr('{"wrong":"value"}'),
            )
        )
    assert path.read_bytes() == b"existing-private-value"
