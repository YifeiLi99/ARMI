import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from armi_admin.application.distribution import ProgramBundle
from armi_admin.install_cli import activate, recover


def bundle(
    root: Path, *, schema_digest: str = "schema-a", launcher: bytes = b"launcher-a"
) -> ProgramBundle:
    root.mkdir(parents=True)
    (root / "program.txt").write_bytes(b"program")
    (root / "ARMI.exe").write_bytes(launcher)
    value = {
        "schema_version": "armi.windows-bundle.v1",
        "product_version": "0.0.0",
        "target": "windows-11-x64",
        "signed": False,
        "database": {
            "postgresql": "18.4",
            "vector": "0.8.6",
            "pg_trgm": "1.6",
            "baseline": "0000",
            "schema_digest": schema_digest,
            "role_policy_digest": "roles-a",
        },
        "package_set_digest": "sha256:" + "1" * 64,
        "files": {
            "program.txt": hashlib.sha256(b"program").hexdigest(),
            "ARMI.exe": hashlib.sha256(launcher).hexdigest(),
        },
    }
    value["package_id"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    (root / "bundle.json").write_text(json.dumps(value), encoding="utf-8")
    return ProgramBundle.read(root)


def test_bundle_rejects_changed_program_and_escaped_inventory(tmp_path):
    program = tmp_path / "program"
    identity = bundle(program)
    identity.verify(program)
    (program / "program.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="INSTALLER-PACKAGE-CORRUPT"):
        identity.verify(program)
    escaping = identity.model_copy(update={"files": {"../outside": "0" * 64}})
    with pytest.raises(ValueError, match="INSTALLER-PACKAGE-BOUNDARY"):
        escaping.verify(program)


def test_activation_rejects_incompatible_database_before_stopping(tmp_path):
    installation = tmp_path / "install"
    old = installation / "versions/old"
    old_bundle = bundle(old)
    previous = old.with_name(old_bundle.package_id)
    old.rename(previous)
    (installation / ".current-version").write_text(
        previous.name + "\n", encoding="ascii"
    )
    staging = installation / "versions/staging"
    new_bundle = bundle(staging, schema_digest="schema-b")
    new = staging.with_name(new_bundle.package_id)
    staging.rename(new)
    with (
        patch("armi_admin.install_cli.registered_environments", return_value=()),
        patch("armi_admin.install_cli._run_admin") as run,
        pytest.raises(ValueError, match="INSTALLER-DATABASE-CONTRACT-INCOMPATIBLE"),
    ):
        activate(installation, new)
    run.assert_not_called()
    assert (installation / ".current-version").read_text().strip() == previous.name
    assert not (installation / ".activation.json").exists()


def test_recovery_rejects_environment_not_owned_by_installation(tmp_path):
    (tmp_path / ".activation.json").write_text(
        json.dumps(
            {
                "schema_version": "armi.program-activation.v2",
                "old_version": None,
                "new_version": "1" * 24,
                "environments": [
                    {
                        "environment_root": str(tmp_path / "foreign"),
                        "program_binding": {
                            "installation_root": str(tmp_path / "versions/old")
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with (
        patch("armi_admin.install_cli.registered_environments", return_value=()),
        pytest.raises(ValueError, match="INSTALLER-ACTIVATION-BOUNDARY"),
    ):
        recover(tmp_path)


def test_environment_index_cannot_register_external_data(tmp_path):
    from armi_admin.application.deployment import (
        register_environment,
        registered_environments,
    )

    program = tmp_path / "versions/current"
    program.mkdir(parents=True)
    (tmp_path / ".current-version").write_text("current\n", encoding="ascii")
    environment = tmp_path / "environments/active"
    register_environment(program, environment)
    assert registered_environments(tmp_path) == (environment,)
    assert (tmp_path / "control/environments.yaml").is_file()
    with pytest.raises(ValueError, match="INSTALLER-ENVIRONMENT-BOUNDARY"):
        register_environment(program, tmp_path.parent / "external")
    assert registered_environments(tmp_path) == (environment,)


def test_process_temporary_and_cache_paths_stay_under_installation(
    tmp_path, monkeypatch
):
    import os
    import tempfile

    from armi_admin.install_cli import configure_process_paths

    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(tempfile, "tempdir", None)
    configure_process_paths(tmp_path)
    assert Path(tempfile.gettempdir()) == tmp_path / "tmp"
    for name in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA"):
        assert Path(os.environ[name]).is_relative_to(tmp_path)


def test_failed_pointer_switch_restores_main_executable_and_version(tmp_path):
    old = tmp_path / "versions/old"
    before = bundle(old)
    previous = old.with_name(before.package_id)
    old.rename(previous)
    (tmp_path / "ARMI.exe").write_bytes(b"launcher-a")
    (tmp_path / ".current-version").write_text(previous.name + "\n", encoding="ascii")
    staging = tmp_path / "versions/staging"
    after = bundle(staging, launcher=b"launcher-b")
    target = staging.with_name(after.package_id)
    staging.rename(target)

    def publish(root, value):
        if value == target.name:
            raise OSError("interrupted before commit")
        (root / ".current-version").write_text(value + "\n", encoding="ascii")

    with (
        patch("armi_admin.install_cli._publish_pointer", side_effect=publish),
        pytest.raises(OSError),
    ):
        activate(tmp_path, target)
    assert (tmp_path / "ARMI.exe").read_bytes() == b"launcher-a"
    assert (tmp_path / ".current-version").read_text().strip() == previous.name
    assert not (tmp_path / ".activation.json").exists()


def test_modified_root_entry_is_not_overwritten(tmp_path):
    old = tmp_path / "versions/old"
    before = bundle(old)
    previous = old.with_name(before.package_id)
    old.rename(previous)
    (tmp_path / ".current-version").write_text(previous.name + "\n", encoding="ascii")
    (tmp_path / "ARMI.exe").write_bytes(b"not the installed program")
    with (
        patch("armi_admin.install_cli.stop_desktop") as stop,
        pytest.raises(ValueError, match="INSTALLER-LAUNCHER-OWNER"),
    ):
        activate(tmp_path, previous)
    stop.assert_not_called()
    assert (tmp_path / "ARMI.exe").read_bytes() == b"not the installed program"


def test_occupied_windows_entry_fails_then_recovers_after_release(tmp_path):
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows executable replacement semantics")
    staging = tmp_path / "versions/staging"
    before = bundle(staging)
    previous = staging.with_name(before.package_id)
    staging.rename(previous)
    activate(tmp_path, previous)
    staging = tmp_path / "versions/staging"
    after = bundle(staging, launcher=b"launcher-b")
    target = staging.with_name(after.package_id)
    staging.rename(target)
    with (tmp_path / "ARMI.exe").open("rb"), pytest.raises(PermissionError):
        activate(tmp_path, target)
    assert (tmp_path / "ARMI.exe").read_bytes() == b"launcher-a"
    assert (tmp_path / ".current-version").read_text().strip() == previous.name
    recover(tmp_path)
    assert not (tmp_path / ".activation.json").exists()
    activate(tmp_path, target)
    assert (tmp_path / "ARMI.exe").read_bytes() == b"launcher-b"


def test_enabled_legacy_startup_is_preserved_and_rewired(tmp_path):
    import subprocess
    import winreg

    from armi_admin.windows_startup import login_startup

    launcher = tmp_path / "ARMI.exe"
    launcher.write_bytes(b"launcher")
    environment = tmp_path / "environments/active"
    legacy = subprocess.list2cmdline(
        [
            str(tmp_path / "armi-desktop.exe"),
            "--environment-root",
            str(environment),
            "--start",
            "--background",
        ]
    )
    with (
        patch("armi_admin.windows_startup.winreg.OpenKey"),
        patch("armi_admin.windows_startup.winreg.CreateKeyEx"),
        patch(
            "armi_admin.windows_startup.winreg.QueryValueEx",
            return_value=(legacy, winreg.REG_SZ),
        ),
        patch("armi_admin.windows_startup.winreg.SetValueEx") as write,
    ):
        assert login_startup(launcher, environment, None)["enabled"] is True
        write.assert_not_called()
        assert login_startup(launcher, environment, None, migrate=True)["enabled"]
        assert write.call_args.args[-1] == subprocess.list2cmdline(
            [str(launcher), "--environment-root", str(environment), "--background"]
        )
