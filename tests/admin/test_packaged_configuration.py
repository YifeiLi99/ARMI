import json
from types import SimpleNamespace
from uuid import uuid7

import armi_local_control.windows_package as windows_package
import pytest
from armi_admin.application.configuration import AdminConfigError, load_admin_config
from armi_admin.application.distribution import BundleDatabase, ProgramBundle


def test_package_upgrade_resolves_resources_without_rewriting_admin_identity(
    tmp_path, monkeypatch
):
    root = tmp_path / "retained"
    environment = root / "environments/active"
    (environment / ".setup").mkdir(parents=True)
    identity = SimpleNamespace(family="ARMI_test", program_root=tmp_path / "package-1")
    database = BundleDatabase(
        postgresql="18.4",
        vector="0.8.6",
        pg_trgm="1.6",
        schema_digest="schema",
        role_policy_digest="roles",
    )
    (environment / ".setup/program.json").write_text(
        json.dumps(
            {"package_family": identity.family, "database": database.model_dump()}
        ),
        encoding="utf-8",
    )
    value = {
        "schema_kind": "armi.admin-config",
        "operator_id": "acceptance-admin",
        "authorized_operations": ["environment_status"],
        "environment_kind": "active",
        "environment_id": str(uuid7()),
        "environment_incarnation": 1,
        "resettable": False,
        "test_controls_enabled": False,
        "environment_root": str(environment),
        "database_locator": "env:ARMI_SECRET_ADMIN_DATABASE",
        "migrator_database_locator": "env:ARMI_SECRET_MIGRATOR_DATABASE",
        "preview_key_locator": "env:ARMI_SECRET_ADMIN_PREVIEW_KEY",
        "expected": {"package_family": identity.family},
        "packaged_postgresql_control": {
            "ownership": "exclusive",
            "data_directory": str(environment / "postgresql/data"),
            "port": 54321,
        },
    }
    config_path = environment / "admin.yaml"
    content = json.dumps(value).encode()
    config_path.write_bytes(content)
    monkeypatch.setattr(windows_package, "package_identity", lambda: identity)
    monkeypatch.setattr(windows_package, "data_root", lambda: root)
    bundle = SimpleNamespace(database=database)
    monkeypatch.setattr(ProgramBundle, "read", lambda _: bundle)
    first, _ = load_admin_config({"ARMI_ADMIN_CONFIG": str(config_path)})
    identity.program_root = tmp_path / "package-2"
    second, _ = load_admin_config({"ARMI_ADMIN_CONFIG": str(config_path)})
    assert (
        second.runtime_defaults_path == identity.program_root / "resources/runtime.yaml"
    )
    assert first.runtime_defaults_path != second.runtime_defaults_path
    second.expected.verify()
    assert first.invocation_identity() == second.invocation_identity()
    assert config_path.read_bytes() == content
    bundle.database = database.model_copy(update={"schema_digest": "incompatible"})
    with pytest.raises(AdminConfigError, match="DATABASE-INCOMPATIBLE"):
        load_admin_config({"ARMI_ADMIN_CONFIG": str(config_path)})
    bundle.database = database
    identity.family = "Other_test"
    with pytest.raises(AdminConfigError, match="PACKAGE-FAMILY"):
        load_admin_config({"ARMI_ADMIN_CONFIG": str(config_path)})
