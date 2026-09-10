"""Installer transport for atomic program activation and data-preserving removal."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid7

from armi_kernel import load_yaml_mapping
from armi_local_control import NativePostgreSQL, private_directory, write_control
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_process import LocalProcessLock

from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.application.configuration import AdminConfig
from armi_admin.application.credentials import AdminCredentialPort
from armi_admin.application.deployment import (
    environment_binding,
    registered_environments,
    replacement_config,
)
from armi_admin.application.distribution import ProgramBundle
from armi_admin.application.installation import SetupIdentity
from armi_admin.composition import bootstrap_admin
from armi_admin.windows_startup import login_startup
from armi_admin.windows_tray import stop_desktop

_PROGRAM_FIELDS = (
    "postgresql_client_root",
    "runtime_defaults_path",
    "creator_web_resources",
    "expected",
)


def _pointer(root: Path) -> str | None:
    path = root / ".current-version"
    if not path.exists():
        return None
    value = path.read_text(encoding="ascii").strip()
    if len(value) != 24 or any(letter not in "0123456789abcdef" for letter in value):
        raise ValueError("INSTALLER-CURRENT-VERSION")
    return value


def _publish_pointer(root: Path, value: str) -> None:
    temporary = root / ".current-version.pending"
    with temporary.open("w", encoding="ascii", newline="\n") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, root / ".current-version")


def _run_admin(program: Path, environment: Path, action: str) -> dict[str, Any]:
    executable = program / "runtime/python/python.exe"
    arguments = [
        str(executable),
        "-I",
        "-B",
        "-m",
        "armi_admin.cli",
        "--config",
        str(environment / "admin.yaml"),
        action,
    ]
    if action != "status":
        arguments.extend(("--idempotency-key", str(uuid7())))
    result = subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=90,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError("INSTALLER-ENVIRONMENT-CONTROL")
    response: dict[str, Any] = json.loads(result.stdout)
    if response.get("status") != "succeeded":
        raise ValueError("INSTALLER-ENVIRONMENT-CONTROL")
    return response


def _program_fields(config: dict[str, Any]) -> dict[str, Any]:
    return {
        **{name: config[name] for name in _PROGRAM_FIELDS},
        "postgresql_installation_root": config["postgresql_control"][
            "installation_root"
        ],
    }


def _restore_fields(config: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    return {
        **config,
        **{name: fields[name] for name in _PROGRAM_FIELDS},
        "postgresql_control": {
            **config["postgresql_control"],
            "installation_root": fields["postgresql_installation_root"],
        },
    }


def recover(root: Path) -> None:
    path = root / ".activation.json"
    if not path.exists():
        return
    journal: dict[str, Any] = json.loads(path.read_bytes())
    if journal.get("schema_version") != "armi.program-activation.v2":
        raise ValueError("INSTALLER-ACTIVATION-JOURNAL")
    registered = set(registered_environments(root))
    for item in journal["environments"]:
        environment = Path(item["environment_root"])
        old_program = Path(item["program_binding"]["installation_root"])
        if (
            environment not in registered
            or has_reparse_point(environment, root=Path(environment.anchor))
            or old_program.parent != root / "versions"
        ):
            raise ValueError("INSTALLER-ACTIVATION-BOUNDARY")
    current = _pointer(root)
    launcher = journal.get("launcher")
    if current == journal["new_version"] and (
        launcher is None
        or (root / "ARMI.exe").read_bytes()
        == (root / "versions" / journal["new_version"] / "ARMI.exe").read_bytes()
    ):
        for item in journal["environments"]:
            login_startup(
                root / "ARMI.exe", Path(item["environment_root"]), None, migrate=True
            )
        if launcher is not None:
            _clean_legacy_launchers(root, journal["old_version"])
        path.unlink()
        return
    if current not in {journal["old_version"], journal["new_version"]}:
        raise ValueError("INSTALLER-ACTIVATION-CONFLICT")
    if launcher is not None:
        backup = root / "control/update/launcher.previous"
        if launcher["previous"]:
            shutil.copyfile(backup, root / "ARMI.exe.pending")
            os.replace(root / "ARMI.exe.pending", root / "ARMI.exe")
        else:
            (root / "ARMI.exe").unlink(missing_ok=True)
        if journal["old_version"] is None:
            (root / ".current-version").unlink(missing_ok=True)
        else:
            _publish_pointer(root, journal["old_version"])
    for item in journal["environments"]:
        environment = Path(item["environment_root"])
        for name, fields in item["configurations"].items():
            if name not in {"admin.yaml", "issuer.yaml"}:
                raise ValueError("INSTALLER-ACTIVATION-CONFIG")
            config_path = environment / name
            current_config = load_yaml_mapping(config_path.read_bytes())
            restored = AdminConfig.model_validate(
                _restore_fields(current_config, fields)
            )
            write_control(config_path, restored.model_dump(mode="json"))
        write_control(environment / ".setup/program.json", item["program_binding"])
    path.unlink()


def configure_process_paths(root: Path) -> None:
    """Keep this installation's child processes and temporary files local."""
    paths = {
        "LOCALAPPDATA": root / "cache/local",
        "APPDATA": root / "cache/roaming",
        "TEMP": root / "tmp",
        "TMP": root / "tmp",
    }
    for path in set(paths.values()):
        private_directory(path)
    os.environ.update({key: str(path) for key, path in paths.items()})
    tempfile.tempdir = str(root / "tmp")


def recover_startup() -> None:
    program = Path(os.environ["ARMI_INSTALLATION_ROOT"])
    if program.parent.name != "versions":
        return
    root = program.parent.parent
    configure_process_paths(root)
    if (root / ".activation.json").exists():
        with LocalProcessLock(root / ".update.lock"):
            recover(root)


def _uninitialized_environment(environment: Path) -> bool:
    state = SetupIdentity.model_validate_json(
        (environment / ".setup/operation.json").read_bytes()
    )
    data = environment / "postgresql/data"
    return (
        state.stage in {"claimed", "configured"}
        and not (environment / "postgresql/cluster.json").exists()
        and (not data.exists() or not any(data.iterdir()))
    )


def _clean_legacy_launchers(
    root: Path, previous: str | None, *, check_only: bool = False
) -> None:
    if previous is None:
        return
    old_program = root / "versions" / previous
    old = ProgramBundle.read(old_program)
    for name in old.files:
        if (
            "/" in name
            or not name.lower().endswith(".exe")
            or name.lower() == "armi.exe"
        ):
            continue
        path = root / name
        if not path.exists():
            continue
        if path.read_bytes() != (old_program / name).read_bytes():
            raise ValueError("INSTALLER-LEGACY-ENTRY-MODIFIED")
        if not check_only:
            path.unlink()


def _check_database(program: Path, bundle: ProgramBundle, environment: Path) -> None:
    if _uninitialized_environment(environment):
        return
    existing = load_yaml_mapping((environment / "admin.yaml").read_bytes())
    config = AdminConfig.model_validate(replacement_config(existing, program, bundle))
    if config.postgresql_control is None:
        raise ValueError("INSTALLER-NATIVE-ENVIRONMENT-REQUIRED")
    database = NativePostgreSQL(
        config.postgresql_control,
        environment_root=environment,
        environment_id=config.environment_id,
    )
    database.execute("start")
    try:
        credentials = AdminCredentialPort(
            locator=config.locator,
            migrator_locator=config.migrator_locator,
            preview_locator=config.preview_locator,
            config_root=environment,
        )
        composition = bootstrap_admin(config, credentials)
        try:
            operation = next(
                item for item in ADMIN_OPERATIONS if item.name == "maintenance"
            )
            request = operation.request.model_validate_json(
                json.dumps(
                    {
                        "environment_id": config.environment_id,
                        "environment_incarnation": config.environment_incarnation,
                        "purpose": "admin.maintenance",
                        "action": "database_check",
                    }
                )
            )
            if operation.invoke(composition.service, request).status != "succeeded":
                raise ValueError("INSTALLER-DATABASE-CHECK")
        finally:
            composition.close()
    finally:
        database.execute("stop")


def activate(root: Path, program: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    program = program.resolve(strict=True)
    bundle = ProgramBundle.read(program)
    bundle.verify(program)
    if program.parent != root / "versions" or program.name != bundle.package_id:
        raise ValueError("INSTALLER-STAGING-BOUNDARY")
    with LocalProcessLock(root / ".update.lock"):
        recover(root)
        previous = _pointer(root)
        environments = tuple(
            environment
            for environment in registered_environments(root)
            if environment.exists()
        )
        if previous is not None:
            old_bundle = ProgramBundle.read(root / "versions" / previous)
            if old_bundle.database != bundle.database:
                raise ValueError("INSTALLER-DATABASE-CONTRACT-INCOMPATIBLE")
            old_bundle.verify(root / "versions" / previous)
        launcher = root / "ARMI.exe"
        if launcher.exists() and (
            previous is None
            or launcher.read_bytes()
            != (root / "versions" / previous / "armi.exe").read_bytes()
        ):
            raise ValueError("INSTALLER-LAUNCHER-OWNER")
        _clean_legacy_launchers(root, previous, check_only=True)
        plans: list[dict[str, Any]] = []
        for environment in environments:
            if has_reparse_point(environment, root=Path(environment.anchor)):
                raise ValueError("INSTALLER-ENVIRONMENT-PATH")
            binding = environment_binding(environment)
            if binding.database != bundle.database:
                raise ValueError("INSTALLER-DATABASE-CONTRACT-INCOMPATIBLE")
            old_program = Path(binding.installation_root)
            if old_program.parent != root / "versions":
                raise ValueError("INSTALLER-ENVIRONMENT-OWNER")
            configurations = {
                name: load_yaml_mapping((environment / name).read_bytes())
                for name in ("admin.yaml", "issuer.yaml")
            }
            login_startup(root / "ARMI.exe", environment, None)
            for value in configurations.values():
                config = AdminConfig.model_validate(value)
                if config.environment_root != environment:
                    raise ValueError("INSTALLER-ENVIRONMENT-OWNER")
            plans.append(
                {
                    "environment_root": str(environment),
                    "program_binding": binding.model_dump(mode="json"),
                    "configurations": {
                        name: _program_fields(value)
                        for name, value in configurations.items()
                    },
                }
            )
        stop_desktop(root / "environments/active")
        # No data or credentials are copied: the journal contains only program
        # paths, package identity, and the unchanged database requirement.
        for plan in plans:
            environment = Path(plan["environment_root"])
            stop_desktop(environment)
            old_program = Path(plan["program_binding"]["installation_root"])
            if previous is not None and not _uninitialized_environment(environment):
                ProgramBundle.read(old_program).verify(old_program)
                _run_admin(old_program, environment, "stop")
            _check_database(program, bundle, environment)
        private_directory(root / "control/update")
        if launcher.exists():
            shutil.copyfile(launcher, root / "control/update/launcher.previous")
        shutil.copyfile(program / "ARMI.exe", root / "ARMI.exe.pending")
        write_control(
            root / ".activation.json",
            {
                "schema_version": "armi.program-activation.v2",
                "old_version": previous,
                "new_version": bundle.package_id,
                "environments": plans,
                "launcher": {"previous": launcher.exists()},
            },
        )
        try:
            for plan in plans:
                environment = Path(plan["environment_root"])
                for name in plan["configurations"]:
                    path = environment / name
                    config = AdminConfig.model_validate(
                        replacement_config(
                            load_yaml_mapping(path.read_bytes()), program, bundle
                        )
                    )
                    write_control(path, config.model_dump(mode="json"))
                write_control(
                    environment / ".setup/program.json",
                    {
                        "installation_root": str(program),
                        "database": bundle.database.model_dump(mode="json"),
                    },
                )
            os.replace(root / "ARMI.exe.pending", launcher)
            _publish_pointer(root, bundle.package_id)
            for environment in environments:
                login_startup(root / "ARMI.exe", environment, None, migrate=True)
            _clean_legacy_launchers(root, previous)
            (root / ".activation.json").unlink()
        except Exception:
            recover(root)
            raise
    return {
        "status": "activated",
        "package_id": bundle.package_id,
        "retained_environments": len(environments),
    }


def uninstall(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    with LocalProcessLock(root / ".update.lock"):
        recover(root)
        stop_desktop(root / "environments/active")
        for environment in registered_environments(root):
            if not environment.exists():
                continue
            binding = environment_binding(environment)
            program = Path(binding.installation_root)
            if program.parent != root / "versions":
                raise ValueError("INSTALLER-ENVIRONMENT-OWNER")
            ProgramBundle.read(program).verify(program)
            stop_desktop(environment)
            if not _uninitialized_environment(environment):
                _run_admin(program, environment, "stop")
            login_startup(program / "ARMI.exe", environment, False)
    return {"status": "stopped", "data_retained": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "uninstall", "recover"))
    parser.add_argument("--installation-root", type=Path, required=True)
    parser.add_argument("--program-root", type=Path)
    args = parser.parse_args()
    try:
        configure_process_paths(args.installation_root.absolute())
        if args.action == "activate":
            if args.program_root is None:
                raise ValueError("INSTALLER-PROGRAM-REQUIRED")
            result = activate(args.installation_root, args.program_root)
        elif args.action == "uninstall":
            result = uninstall(args.installation_root)
        else:
            with LocalProcessLock(args.installation_root / ".update.lock"):
                recover(args.installation_root)
            result = {"status": "reconciled"}
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, ValueError) and str(error).startswith("INSTALLER-")
            else "INSTALLER-OPERATION-FAILED"
        )
        print(json.dumps({"status": "failed", "error_code": code}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
