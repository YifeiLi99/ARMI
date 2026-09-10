import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from armi_admin.application.distribution import ProgramBundle
from armi_admin.install_cli import activate, recover


def bundle(root: Path, *, schema_digest: str = "schema-a") -> ProgramBundle:
    root.mkdir(parents=True)
    (root / "program.txt").write_bytes(b"program")
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
        "files": {"program.txt": hashlib.sha256(b"program").hexdigest()},
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
                "schema_version": "armi.program-activation.v1",
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
