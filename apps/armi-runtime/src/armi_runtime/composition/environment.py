"""Validated environment-root loading for the Runtime CLI."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path

from armi_kernel.application import CredentialLocator, CredentialPort

from .configuration import (
    DeploymentProfile,
    EffectiveConfig,
    EnvironmentFileCredentialPort,
    PreflightRequirements,
    load_effective_config,
    preflight_config,
)
from .configuration.paths import canonical_absolute, has_reparse_point
from .credential_scope import ScopedCredentialPort
from .runtime_errors import RuntimeViolation

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"


@dataclass(frozen=True, slots=True)
class PreparedEnvironment:
    root: Path
    data_root: Path
    secrets_root: Path
    effective: EffectiveConfig
    credential_port: CredentialPort


def prepare_environment(
    environment_root: Path,
    *,
    environment: Mapping[str, str] | None = None,
    credential_scope: Mapping[str, str] | None = None,
) -> PreparedEnvironment:
    root = canonical_absolute(environment_root, code="CFG-ENV-ROOT")
    if not root.is_dir() or has_reparse_point(root, root=root):
        raise RuntimeViolation(
            "CFG-ENV-ROOT",
            "environment root must be an existing non-reparse directory",
        )
    environment_path = root / "environment.toml"
    data_root = root / "data"
    secrets_root = root / "secrets"
    for path, code in (
        (environment_path, "CFG-ENV-FILE"),
        (data_root, "CFG-DATA-ROOT"),
        (secrets_root, "SEC-SECRET-ROOT"),
    ):
        if not path.exists():
            raise RuntimeViolation(code, "a required environment-root entry is missing")
    if (
        not environment_path.is_file()
        or not data_root.is_dir()
        or not secrets_root.is_dir()
        or has_reparse_point(environment_path, root=root)
        or has_reparse_point(data_root, root=root)
        or has_reparse_point(secrets_root, root=root)
    ):
        raise RuntimeViolation(
            "CFG-ENV-LAYOUT",
            "environment-root entries must be ordinary files and directories",
        )
    current_environment = dict(environment if environment is not None else os.environ)
    defaults = files(_RESOURCE_PACKAGE).joinpath("runtime.defaults.toml")
    with as_file(defaults) as defaults_path:
        effective = load_effective_config(
            defaults_path=defaults_path,
            environment_path=environment_path,
            environment=current_environment,
        )
    if effective.config.environment.data_root != data_root.resolve():
        raise RuntimeViolation(
            "CFG-DATA-ROOT",
            "configured data root must equal environment-root/data",
        )
    profile = DeploymentProfile.create(
        allowed_data_roots=(data_root,),
        allowed_secret_roots=(secrets_root,),
    )
    preflight_config(
        effective,
        profile=profile,
        requirements=PreflightRequirements(),
        environment=current_environment,
    )
    credential_delegate = EnvironmentFileCredentialPort(
        environment=current_environment,
        secret_roots=profile.allowed_secret_roots,
        maximum_bytes=profile.maximum_secret_bytes,
    )
    requested_scope = (
        {"database.runtime": "database.runtime"}
        if credential_scope is None
        else dict(credential_scope)
    )
    allowed_locators: dict[str, CredentialLocator] = {}
    for purpose, locator_name in requested_scope.items():
        locator = effective.config.secret_locators.get(locator_name)
        if locator is not None:
            allowed_locators[purpose] = locator
    credential_port = ScopedCredentialPort(
        credential_delegate,
        allowed=allowed_locators,
    )
    return PreparedEnvironment(
        root=root,
        data_root=data_root,
        secrets_root=secrets_root,
        effective=effective,
        credential_port=credential_port,
    )


__all__ = ("PreparedEnvironment", "prepare_environment")
