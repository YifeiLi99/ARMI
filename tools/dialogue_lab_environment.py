"""Prepare one new isolated source environment using the official owner installers."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any
from uuid import uuid7

import psycopg
from armi_admin.application import admin_program_identity
from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.application.configuration import AdminConfig
from armi_admin.application.postgresql_bootstrap import (
    apply_policy,
    inspect_policy,
    physical_role_name,
)
from armi_kernel import load_yaml_file
from armi_local_control import (
    NativePostgreSQL,
    PostgreSQLControlBinding,
    free_loopback_port,
    private_directory,
    write_control,
)
from armi_local_control.configuration.paths import has_reparse_point
from psycopg.conninfo import make_conninfo

from tools.dialogue_lab import DialogueLab
from tools.dialogue_lab_support import ROOT, LabError


def initialize(
    root: Path, *, anchor: Path, creator_resources: Path, activation_weight: int = 50
) -> dict[str, Any]:
    from armi_admin.application.setup_operations import SetupAnchor
    from armi_local_control.configuration.models import AutonomyConfig

    autonomy = AutonomyConfig(
        enabled=True, outlet="creator_web", activation_weight=activation_weight
    )

    personality = SetupAnchor.model_validate(
        load_yaml_file(anchor.resolve(strict=True))
    )
    personality.domain()
    resources = creator_resources.resolve(strict=True)
    if (
        not (resources / "manifest.json").is_file()
        or not (resources / "static/index.html").is_file()
    ):
        raise LabError("LAB-CREATOR-BUILD-REQUIRED")
    root = root.resolve()
    experiments = (ROOT / ".tmp/dialogue-lab").resolve()
    if (
        root == experiments
        or not root.is_relative_to(experiments)
        or root.exists()
        or has_reparse_point(root, root=Path(root.anchor))
    ):
        raise LabError("LAB-NEW-ROOT-REQUIRED-BELOW-.tmp/dialogue-lab")
    distribution = (
        ROOT / ".armi-tools/installs/postgresql-native/18.4-vector-0.8.6-utf8/pgsql"
    )
    if not (distribution / "lib/vector.dll").is_file():
        raise LabError("LAB-POSTGRESQL-UNAVAILABLE")
    environment_id, creator_id, delegate_id, birth_id = (uuid7() for _ in range(4))
    port = free_loopback_port()
    creator_port = free_loopback_port()
    while creator_port == port:
        creator_port = free_loopback_port()
    private_directory(root)
    private_directory(root / "secrets")
    (root / "bootstrap").mkdir()
    (root / "data").mkdir()

    def secret(name: str, value: str) -> str:
        path = root / "secrets" / name
        path.write_text(value, encoding="utf-8")
        return f"file:{path.as_posix()}"

    passwords = {
        role: secrets.token_urlsafe(48) for role in ("runtime", "admin", "migrator")
    }
    locators = {
        role: secret(
            role + "-database",
            make_conninfo(
                host="127.0.0.1",
                port=port,
                dbname="postgres",
                user=physical_role_name(environment_id, role),
                password=passwords[role],
                connect_timeout=10,
            ),
        )
        for role in passwords
    }
    preview = secret("admin-preview", secrets.token_urlsafe(48))
    bearer = secret("creator-bearer", secrets.token_urlsafe(48))
    identity = secret("data-rights-identity", secrets.token_urlsafe(48))
    interaction = secret("interaction", secrets.token_urlsafe(48))
    binding = PostgreSQLControlBinding(
        ownership="exclusive",
        installation_root=distribution.resolve(),
        data_directory=root / "postgresql/data",
        port=port,
    )
    config = AdminConfig.model_validate(
        {
            "schema_kind": "armi.admin-config",
            "operator_id": "source-dialogue-lab",
            "authorized_operations": [operation.name for operation in ADMIN_OPERATIONS],
            "environment_kind": "system_test",
            "environment_id": str(environment_id),
            "environment_incarnation": 1,
            "resettable": True,
            "test_controls_enabled": True,
            "environment_root": root,
            "experiment_root": experiments,
            "postgresql_client_root": distribution.resolve(),
            "postgresql_control": binding,
            "runtime_defaults_path": ROOT / "configs/runtime.yaml",
            "creator_web_resources": resources,
            "database_locator": locators["admin"],
            "migrator_database_locator": locators["migrator"],
            "preview_key_locator": preview,
            "expected": admin_program_identity(),
        }
    )
    write_control(root / "admin.yaml", config.model_dump(mode="json"))
    write_control(
        root / "environment.yaml",
        {
            "environment": {
                "environment_id": str(environment_id),
                "data_root": str(root / "data"),
            },
            "creator": {"port": creator_port},
            "autonomy": autonomy.model_dump(),
            "secret_locators": {
                "database.runtime": locators["runtime"],
                "database.migrator": locators["migrator"],
                "creator.bearer": bearer,
                "data_rights.identity_token_key": identity,
                **{
                    name: f"file:{(root / 'secrets' / ('provider-' + name)).as_posix()}"
                    for name in (
                        "mood.jev_api_key",
                        "model.qwen_api_key",
                        "model.deepseek_api_key",
                    )
                },
            },
        },
    )
    delegate = {
        "delegate_id": str(delegate_id),
        "creator_party_id": str(creator_id),
        "credential_locator": interaction,
        "scopes": ["interaction.read", "interaction.write"],
    }
    write_control(
        root / "interaction-access.yaml",
        {
            "schema_kind": "armi.interaction-access",
            "environment_id": str(environment_id),
            "delegates": [delegate],
        },
    )
    write_control(
        root / "client.yaml",
        {
            **delegate,
            "schema_kind": "armi.interaction-client",
            "environment_id": str(environment_id),
            "environment_root": str(root),
            "endpoint": f"http://127.0.0.1:{creator_port}",
        },
    )
    write_control(
        root / "bootstrap/birth-manifest.json",
        {
            "schema_kind": "armi.birth-manifest",
            "environment_id": str(environment_id),
            "birth_request_id": str(birth_id),
            "creator_party_id": str(creator_id),
            "idempotency_key": str(birth_id),
            "personality_anchor": personality.model_dump(),
        },
    )
    manager = NativePostgreSQL(
        binding, environment_root=root, environment_id=str(environment_id)
    )
    bootstrap_password = secrets.token_urlsafe(48)
    initialized = False
    try:
        manager.initialize(username="armi_lab_bootstrap", password=bootstrap_password)
        initialized = True
        manager.execute("start")
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            dbname="postgres",
            user="armi_lab_bootstrap",
            password=bootstrap_password,
        ) as connection:
            apply_policy(connection, environment_id=environment_id, passwords=passwords)
            inspect_policy(connection, environment_id=environment_id)
        lab = DialogueLab(root)
        result = lab.admin(
            "environment_initialize",
            {"birth_mode": "manifest", "idempotency_key": str(uuid7())},
        )
    finally:
        if initialized:
            manager.execute("stop")
    return {
        "status": "prepared",
        "root": str(root),
        "initialization": result,
        "providers_configured": False,
        "model_calls": 0,
    }
