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


def test_begin_login_never_creates_binding_or_onebot_before_scan(tmp_path):
    service = application(tmp_path / "environments/active")
    node = NapCatNode(service.root)
    node.control.mkdir()
    calls = []

    def invoke(operation, arguments):
        calls.append((operation, arguments))
        return {"status": "succeeded", "result": {"version": "v1", "values": {}}}

    with (
        patch.object(service, "invoke", side_effect=invoke),
        patch("armi_admin.application.installation.socket.create_connection"),
    ):
        result = service._begin_napcat_login(
            SetupNapcatRequest(
                action="prepare", creator_user_id=98765, enabled=True, open_login=True
            )
        )
    assert result["status"] == "awaiting_login"
    assert json.loads(node.login_path.read_bytes()) == {"creator_user_id": 98765}
    assert (
        json.loads((node.root / "config/webui.json").read_bytes())["autoLoginAccount"]
        == ""
    )
    assert list((node.root / "config").glob("onebot*")) == []
    assert not (service.root / "channels/qq-napcat.yaml").exists()
    assert [op for op, _ in calls] == [
        "configuration",
        "environment_stop",
        "environment_start",
        "maintenance",
    ]


@pytest.mark.parametrize("account", [None, 12345])
def test_completion_uses_only_online_account_and_is_idempotent(tmp_path, account):
    service = application(tmp_path / "environments/active")
    node = NapCatNode(service.root)
    node.control.mkdir()
    node.login_path.write_text(json.dumps({"creator_user_id": 98765}))
    with (
        patch.object(service, "_read", return_value=Mock(stage="ready")),
        patch.object(NapCatNode, "login_account", return_value=account),
        patch.object(
            service, "_configure_napcat", return_value={"status": "ready"}
        ) as configure,
    ):
        result = service.napcat(SetupNapcatRequest(action="complete"))
        if account is None:
            assert result["status"] == "awaiting_login"
            configure.assert_not_called()
            assert node.login_path.exists()
        else:
            assert result["account_id"] == account
            assert configure.call_args.kwargs["account_id"] == account
            assert configure.call_args.args[0].creator_user_id == 98765
            assert not node.login_path.exists()
            service.napcat(SetupNapcatRequest(action="complete"))
            assert configure.call_count == 1


def test_scanning_creator_account_is_rejected_without_binding(tmp_path):
    service = application(tmp_path / "environments/active")
    node = NapCatNode(service.root)
    node.control.mkdir()
    node.login_path.write_text(json.dumps({"creator_user_id": 98765}))
    with (
        patch.object(service, "_read", return_value=Mock(stage="ready")),
        patch.object(NapCatNode, "login_account", return_value=98765),
        patch.object(service, "_configure_napcat") as configure,
        pytest.raises(SetupError, match="ACCOUNT-IDENTITIES"),
    ):
        service.napcat(SetupNapcatRequest(action="complete"))
    configure.assert_not_called()
    assert not node.login_path.exists()


def test_uncertain_configuration_is_not_replayed_by_login_poll(tmp_path):
    service = application(tmp_path / "environments/active")
    node = NapCatNode(service.root)
    node.control.mkdir()
    node.login_path.write_text(json.dumps({"creator_user_id": 98765}))
    with (
        patch.object(service, "_read", return_value=Mock(stage="ready")),
        patch.object(NapCatNode, "login_account", return_value=12345),
        patch.object(
            service,
            "_configure_napcat",
            side_effect=SetupError("NAPCAT-ADMIN-CONFIGURATION-UNCONFIRMED"),
        ) as configure,
    ):
        with pytest.raises(SetupError, match="UNCONFIRMED"):
            service.napcat(SetupNapcatRequest(action="complete"))
        service.napcat(SetupNapcatRequest(action="complete"))
    assert configure.call_count == 1


@pytest.mark.parametrize(
    "account,expected",
    [(None, "login_required"), (12345, "ready"), (45678, "misconfigured")],
)
def test_bound_login_recovery_observes_health_without_reconfiguring(
    tmp_path, account, expected
):
    service = application(tmp_path / "environments/active")
    calls = []

    def invoke(operation, arguments):
        calls.append((operation, arguments))
        return {
            "status": "succeeded",
            "result": {
                "values": {
                    "account_id": 12345,
                    "creator_user_id": 98765,
                    "enabled": True,
                }
            }
            if operation == "configuration"
            else {"state": "ready"},
        }

    with (
        patch.object(service, "_read", return_value=Mock(stage="ready")),
        patch.object(NapCatNode, "installed", return_value=True),
        patch.object(NapCatNode, "login_account", return_value=account),
        patch.object(service, "invoke", side_effect=invoke),
        patch.object(service, "_configure_napcat") as configure,
    ):
        for _ in range(2):
            assert (
                service.napcat(SetupNapcatRequest(action="complete"))["status"]
                == expected
            )
    configure.assert_not_called()
    assert all(op in {"configuration", "maintenance"} for op, _ in calls)


def test_repeated_prepare_of_bound_account_never_stops_or_reconfigures(tmp_path):
    service = application(tmp_path / "environments/active")
    webui = service.root / "tools/napcat/config/webui.json"
    webui.parent.mkdir(parents=True)
    webui.write_text(json.dumps({"port": 3001}))
    with (
        patch("armi_admin.application.installation.socket.create_connection"),
        patch.object(
            service,
            "_napcat_admin",
            return_value={
                "values": {
                    "account_id": 12345,
                    "creator_user_id": 98765,
                    "enabled": True,
                }
            },
        ) as admin,
        patch.object(
            service, "_napcat_connection", return_value={"status": "login_required"}
        ),
    ):
        service._begin_napcat_login(
            SetupNapcatRequest(
                action="prepare", creator_user_id=98765, enabled=True, open_login=True
            )
        )
    assert [call.args[0] for call in admin.call_args_list] == [
        "configuration",
        "environment_start",
        "maintenance",
    ]


def test_login_page_hides_install_progress_and_offers_recovery():
    from armi_admin.desktop import Desktop

    desktop = object.__new__(Desktop)
    desktop.qq_installed = False
    desktop.qq_component = Mock()
    desktop.qq_progress = Mock()
    desktop.qq_button = Mock()
    desktop.qq_creator = Mock()
    desktop.qq_status = Mock()
    desktop._qq_display(
        {
            "status": "login_required",
            "installed": True,
            "version": "4.18.9",
            "account_id": 12345,
        }
    )
    desktop.qq_progress.pack_forget.assert_called_once()
    desktop.qq_progress.pack.assert_not_called()
    assert desktop.qq_action == "open_login"
    assert "已安装" in desktop.qq_component.set.call_args.args[0]
    assert "下一步" in desktop.qq_status.set.call_args.args[0]
    assert desktop.qq_button.configure.call_args.kwargs["state"] == "normal"


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

    request = SetupNapcatRequest(action="prepare", creator_user_id=98765)
    with patch.object(service, "invoke", side_effect=invoke):
        service._configure_napcat(request, account_id=12345)
        tokens = {
            path.name: path.read_bytes()
            for path in (service.root / "secrets").iterdir()
        }
        service._configure_napcat(request, account_id=12345)
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
            SetupNapcatRequest(action="prepare", creator_user_id=98765),
            account_id=12345,
        )
    assert invoke.call_count == 2
    assert list((service.root / "secrets").iterdir()) == []
    assert not (service.root / "tools/napcat/config").exists()
