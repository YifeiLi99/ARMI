from unittest.mock import Mock

import armi_local_control.windows_package as windows_package
import pytest
from armi_admin import composition
from armi_admin.application import deployment
from armi_admin.application.installation import SetupPaths
from armi_admin.setup_cli import SetupRequest, dispatch
from pydantic import ValidationError


@pytest.fixture
def removal(tmp_path, monkeypatch):
    paths = SetupPaths(
        installation_root=tmp_path,
        environment_root=tmp_path / "environments/active",
    )
    monkeypatch.setattr(deployment, "installed_root", lambda _: tmp_path)
    monkeypatch.setattr(
        deployment, "registered_environments", lambda _: [paths.environment_root]
    )
    service = composition.bootstrap_setup(paths)
    admin = Mock()
    admin.invoke.return_value = {"status": "succeeded"}
    monkeypatch.setattr(composition, "bootstrap_setup", Mock(return_value=admin))
    native = Mock(return_value={"status": "uninstall_requested"})
    monkeypatch.setattr(windows_package, "uninstall", native)
    return service, admin, native


@pytest.mark.parametrize("delete_data", [None, False, True])
def test_uninstall_stops_through_admin_and_requires_explicit_cleanup(
    removal, delete_data
):
    service, admin, native = removal
    payload = {"action": "uninstall"}
    if delete_data is not None:
        payload["delete_data"] = delete_data
    result = dispatch(service, SetupRequest.model_validate(payload))
    assert result["status"] == "uninstall_requested"
    assert admin.invoke.call_args.args[0] == "environment_stop"
    native.assert_called_once_with(delete_data=delete_data is True)


def test_uninstall_does_not_delete_or_deploy_when_stop_fails(removal):
    service, admin, native = removal
    admin.invoke.return_value = {"status": "failed"}
    result = dispatch(service, SetupRequest(action="uninstall", delete_data=True))
    assert result == {
        "status": "failed",
        "error_code": "UNINSTALL-ENVIRONMENT-STOP-UNCONFIRMED",
    }
    native.assert_not_called()


def test_source_uninstall_is_unavailable(tmp_path, monkeypatch):
    service = composition.bootstrap_setup(
        SetupPaths(
            installation_root=tmp_path,
            environment_root=tmp_path / "environments/active",
        )
    )
    native = Mock()
    monkeypatch.setattr(windows_package, "uninstall", native)
    result = dispatch(service, SetupRequest(action="uninstall"))
    assert result["error_code"] == "UNINSTALL-MSIX-REQUIRED"
    native.assert_not_called()


@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_cleanup_rejects_ambiguous_values(value):
    with pytest.raises(ValidationError):
        SetupRequest.model_validate({"action": "uninstall", "delete_data": value})
