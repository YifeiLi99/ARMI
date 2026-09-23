from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid7

import pytest
from armi_admin.application.installation import SetupApplication, SetupError, SetupPaths
from armi_admin.setup_cli import SetupRequest, dispatch
from armi_kernel import load_yaml_mapping


def application(root: Path) -> SetupApplication:
    return SetupApplication(
        SetupPaths(
            environment_root=root,
            installation_root=root.parent.parent,
        ),
        Mock(),
    )


def test_installer_rejects_existing_environment_without_modifying_it(tmp_path):
    root = tmp_path / "environments/existing"
    root.mkdir(parents=True)
    marker = root / "environment.yaml"
    marker.write_bytes(b"existing configuration")
    with pytest.raises(SetupError, match="SETUP-NEW-EMPTY-ENVIRONMENT-REQUIRED"):
        application(root).prepare(operation_id=str(uuid7()))
    assert marker.read_bytes() == b"existing configuration"
    assert not (root / ".setup").exists()


def test_interrupted_configuration_keeps_identity_and_rejects_other_operation(tmp_path):
    service = application(tmp_path / "environments/新环境 with spaces")
    operation_id = str(uuid7())
    with (
        patch.object(service, "check"),
        patch.object(service, "_configure", side_effect=OSError("interrupted")),
        pytest.raises(OSError),
    ):
        service.prepare(operation_id=operation_id)
    before = service.status()
    with (
        patch.object(service, "check"),
        pytest.raises(SetupError, match="SETUP-OPERATION-MISMATCH"),
    ):
        service.prepare(operation_id=str(uuid7()))
    assert service.status() == before
    assert before["operation_id"] == operation_id


def test_initial_bindings_isolate_creator_signing_credentials(tmp_path):
    service = application(tmp_path / "environments/new")
    with (
        patch.object(service, "check"),
        patch.object(service, "_configure", side_effect=OSError("interrupted")),
        pytest.raises(OSError),
    ):
        service.prepare(operation_id=str(uuid7()))
    with (
        patch(
            "armi_admin.application.installation.ProgramBundle.read",
            return_value=Mock(database=Mock(model_dump=Mock(return_value={}))),
        ),
    ):
        service._configure(service._read())
    admin = load_yaml_mapping((service.root / "admin.yaml").read_bytes())
    issuer = load_yaml_mapping((service.root / "issuer.yaml").read_bytes())
    assert admin["authorization_signing_key_locator"] is None
    operations = admin["authorized_operations"]
    assert isinstance(operations, list)
    assert "authorization_approve" not in operations
    assert issuer["authorized_operations"] == ["authorization_approve"]
    assert issuer["authorization_public_key"] == admin["authorization_public_key"]
    assert not (service.root / "bootstrap/birth-manifest.json").exists()


def test_setup_transport_redacts_input_from_failure(tmp_path):
    service = application(tmp_path / "environments/new")
    with patch.object(service, "prepare", side_effect=ValueError("private input")):
        result = dispatch(
            service, SetupRequest(action="prepare", operation_id=str(uuid7()))
        )
    assert result["status"] == "failed"
    assert result["error_code"] == "SETUP-OPERATION-FAILED"
    assert result["diagnostic"]["type"] == "ValueError"
    assert "private input" not in str(result)
    assert all(
        set(frame) == {"file", "line", "function"}
        for frame in result["diagnostic"]["frames"]
    )


def test_standalone_environment_stays_inside_explicit_program_root(tmp_path):
    program = tmp_path / "app"
    environment = program / "environments/active"
    assert SetupPaths(environment_root=environment, installation_root=program)
    for forbidden in (
        tmp_path.parent / "external",
        program / "data",
        tmp_path / "environments/../external",
    ):
        with pytest.raises(ValueError, match="SETUP-ENVIRONMENT-BOUNDARY"):
            SetupPaths(environment_root=forbidden, installation_root=program)


def test_installed_control_records_are_inside_installation(tmp_path):
    from armi_local_control import environment_control_root
    from armi_local_control.lifecycle import environment_control_lock

    environment = tmp_path / "environments/active"
    expected = tmp_path / "control/environments/environment-id"
    assert environment_control_root(environment, "environment-id") == expected
    with environment_control_lock(environment, "environment-id"):
        assert (expected / "environment-control.lock").exists()
    assert not (tmp_path.parent / ".armi-admin/environment-id").exists()


def test_database_rebuild_rejects_unregistered_target_before_opening_database(tmp_path):
    service = application(tmp_path / "environments/active")
    bundle = Mock()
    with (
        patch(
            "armi_admin.application.installation.ProgramBundle.read",
            return_value=bundle,
        ),
        patch(
            "armi_admin.application.installation.package_identity", return_value=Mock()
        ),
        patch(
            "armi_admin.application.deployment.installed_root", return_value=tmp_path
        ),
        patch(
            "armi_admin.application.installation.registered_environments",
            return_value=(),
        ),
        patch.object(service, "_database") as database,
        pytest.raises(SetupError, match="SETUP-REBUILD-REGISTERED-MSIX-REQUIRED"),
    ):
        service.rebuild_database()
    database.assert_not_called()


def test_database_rebuild_rejects_current_contract_before_opening_database(tmp_path):
    service = application(tmp_path / "environments/active")
    service.control.mkdir(parents=True)
    state = Mock(stage="ready")
    database_contract = Mock()
    bundle = Mock(database=database_contract)
    with (
        patch(
            "armi_admin.application.installation.ProgramBundle.read",
            return_value=bundle,
        ),
        patch(
            "armi_admin.application.installation.package_identity",
            return_value=Mock(family="same"),
        ),
        patch(
            "armi_admin.application.deployment.installed_root", return_value=tmp_path
        ),
        patch(
            "armi_admin.application.installation.registered_environments",
            return_value=(service.root,),
        ),
        patch(
            "armi_admin.application.installation.environment_binding",
            return_value=Mock(package_family="same", database=database_contract),
        ),
        patch.object(service, "_read", return_value=state),
        patch.object(service, "_database") as database,
        pytest.raises(SetupError, match="SETUP-REBUILD-CONTRACT-CURRENT"),
    ):
        service.rebuild_database()
    database.assert_not_called()
