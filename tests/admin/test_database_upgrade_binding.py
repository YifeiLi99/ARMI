from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from armi_admin.application.database_upgrade import database_upgrade
from armi_admin.application.installation import SetupError, SetupPaths

from tests.admin.test_admin_control import _config


@pytest.mark.parametrize(
    "action,delta,other_environment,succeeds",
    [
        ("apply", 1, False, True),
        ("apply", 0, False, True),
        ("status", 1, False, False),
        ("check", 1, False, False),
        ("apply", 2, False, False),
        ("apply", -1, False, False),
        ("apply", 1, True, False),
    ],
)
def test_explicit_upgrade_recovers_only_the_next_registered_incarnation(
    tmp_path, action, delta, other_environment, succeeds
):
    config = _config(tmp_path).model_copy(
        update={"environment_root": tmp_path / "environments/active"}
    )
    (config.environment_root / ".setup").mkdir(parents=True)
    identity = Mock()
    identity.model_dump.return_value = {}
    bundle = Mock(database=identity)
    bound = SimpleNamespace(package_family=None, database=identity)
    connection = MagicMock()
    role = config.expected_role.removesuffix("_admin") + (
        "_migrator" if action == "apply" else "_admin"
    )
    connection.execute.return_value.fetchone.return_value = (role, role)
    controller = Mock()
    controller.maintain_database.side_effect = lambda execute: execute()
    environment = SimpleNamespace(
        environment_id="another-environment"
        if other_environment
        else config.environment_id,
        environment_kind=config.environment_kind.value,
        incarnation=config.environment_incarnation + delta,
    )
    module = "armi_admin.application.database_upgrade."
    with (
        patch(module + "ProgramBundle.read", return_value=bundle),
        patch(module + "upgrade_target", return_value={}),
        patch(
            module + "load_admin_config", return_value=(config, tmp_path / "admin.yaml")
        ),
        patch(module + "verify_local_owner"),
        patch(module + "environment_binding", return_value=bound),
        patch(module + "package_identity", return_value=None),
        patch(module + "verify_upgrade_resources"),
        patch(module + "prepare_configuration_upgrade", return_value=[]),
        patch(module + "AdminCredentialPort"),
        patch(module + "LocalEnvironmentController", return_value=controller),
        patch(module + "psycopg.connect") as connect,
        patch(module + "RuntimeFoundationAdminAdapter") as adapter,
        patch(module + "apply_upgrade", return_value={"status": "current"}) as upgrade,
        patch(module + "synchronize_environment_incarnation") as synchronize,
    ):
        connect.return_value.__enter__.return_value = connection
        adapter.return_value.environment.return_value = environment
        paths = SetupPaths(
            environment_root=config.environment_root, installation_root=tmp_path
        )
        if succeeds:
            assert database_upgrade(paths, action)["status"] == "succeeded"
            upgrade.assert_called_once_with(connection)
            synchronize.assert_called_once_with(config, environment.incarnation)
        else:
            with pytest.raises(SetupError, match="UPGRADE-ENVIRONMENT"):
                database_upgrade(paths, action)
            upgrade.assert_not_called()
            synchronize.assert_not_called()
