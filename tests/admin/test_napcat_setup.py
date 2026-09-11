import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from armi_admin.application.installation import (
    SetupApplication,
    SetupError,
    SetupNapcatRequest,
    SetupPaths,
)
from armi_admin.setup_cli import SetupRequest, dispatch
from armi_local_control.napcat_node import NapCatNode
from pydantic import ValidationError


def application(root: Path) -> SetupApplication:
    (root / "secrets").mkdir(parents=True)
    return SetupApplication(
        SetupPaths(environment_root=root, installation_root=root.parent.parent), Mock()
    )


def test_install_only_does_not_enable_or_start_qq(tmp_path):
    service = application(tmp_path / "environments/active")
    with (
        patch.object(
            service, "_read", return_value=Mock(stage="ready", environment_id="test")
        ),
        patch.object(NapCatNode, "install") as install,
        patch.object(service, "invoke") as invoke,
    ):
        result = dispatch(
            service,
            SetupRequest(action="napcat", napcat=SetupNapcatRequest(action="prepare")),
        )
    install.assert_called_once_with("test")
    invoke.assert_not_called()
    assert "accounts_required" in str(result)
    assert not (service.root / "channels/qq-napcat.yaml").exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"enabled": True},
        {"account_id": 123, "creator_user_id": 123},
        {"open_login": True},
        {"account_id": "123"},
    ],
)
def test_enable_requires_explicit_distinct_accounts(fields):
    with pytest.raises(ValidationError):
        SetupNapcatRequest(action="prepare", **fields)


def test_configuration_uses_owner_and_preserves_generated_credentials(tmp_path):
    service = application(tmp_path / "environments/active")
    saved = {}
    calls = []

    def invoke(operation, arguments):
        calls.append((operation, arguments))
        if operation == "configuration":
            if arguments["action"] == "read":
                return {
                    "status": "succeeded",
                    "result": {"version": "v1", "values": saved.copy()},
                }
            if arguments["action"] == "apply":
                saved.update(arguments["document"])
        return {"status": "succeeded", "result": {}}

    request = SetupNapcatRequest(
        action="prepare", account_id=12345, creator_user_id=98765
    )
    with patch.object(service, "invoke", side_effect=invoke):
        service._configure_napcat(request)
        tokens = {
            path.name: path.read_bytes()
            for path in (service.root / "secrets").iterdir()
        }
        service._configure_napcat(request)
    assert tokens == {
        path.name: path.read_bytes() for path in (service.root / "secrets").iterdir()
    }
    assert saved["allowed_groups"] == {}
    assert saved["reply_in_groups"] is False
    assert saved["reply_to_other_private_users"] is False
    assert saved["enabled"] is False
    assert "environment_start" not in [operation for operation, _ in calls]
    config = service.root / "tools/napcat/config"
    network = json.loads((config / "onebot11_12345.json").read_bytes())["network"]
    assert network["httpServers"][0]["host"] == "127.0.0.1"
    assert network["httpClients"][0]["url"].startswith("http://127.0.0.1:")
    assert network["httpServers"][0]["token"] != network["httpClients"][0]["token"]


def test_unconfirmed_stop_does_not_write_configuration_or_credentials(tmp_path):
    service = application(tmp_path / "environments/active")
    with (
        patch.object(
            service,
            "invoke",
            side_effect=[
                {"status": "succeeded", "result": {"version": "v1", "values": {}}},
                {"status": "unknown"},
            ],
        ) as invoke,
        pytest.raises(SetupError, match="STOP-UNCONFIRMED"),
    ):
        service._configure_napcat(
            SetupNapcatRequest(
                action="prepare", account_id=12345, creator_user_id=98765
            )
        )
    assert invoke.call_count == 2
    assert list((service.root / "secrets").iterdir()) == []
    assert not (service.root / "tools/napcat/config").exists()
