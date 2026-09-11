"""Local owner authority requires the actual private machine binding."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid7

import pytest
from armi_admin.application.configuration import AdminConfig
from armi_admin.application.installation import SetupIdentity
from armi_admin.application.local_authority import verify_local_owner
from armi_local_control import private_directory


def binding(root: Path) -> tuple[AdminConfig, Path]:
    private_directory(root)
    private_directory(root / "secrets")
    private_directory(root / ".setup")
    identity = SetupIdentity(
        operation_id=str(uuid7()),
        environment_id=str(uuid7()),
        creator_party_id=str(uuid7()),
        delegate_id=str(uuid7()),
        birth_request_id=str(uuid7()),
        postgresql_port=15432,
        creator_port=15433,
        stage="ready",
    )
    (root / ".setup/operation.json").write_text(
        identity.model_dump_json(), encoding="utf-8"
    )
    path = root / "admin.yaml"
    path.write_text("isolated test", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
        (root / ".setup/operation.json").chmod(0o600)
    config = Mock(spec=AdminConfig)
    config.operator_id = "native-local-admin"
    config.environment_id = identity.environment_id
    config.environment_root = root
    return config, path


def test_private_binding_accepts_current_user_without_elevation(tmp_path: Path) -> None:
    config, path = binding(tmp_path / "environment")
    verify_local_owner(config, path)


def test_binding_rejects_different_environment_or_operator(tmp_path: Path) -> None:
    config, path = binding(tmp_path / "environment")
    config.environment_id = str(uuid7())
    with pytest.raises(ValueError, match="ADMIN-LOCAL-OWNER-ENVIRONMENT"):
        verify_local_owner(config, path)
    config.operator_id = "delegated-agent"
    with pytest.raises(ValueError, match="ADMIN-LOCAL-OWNER-BINDING"):
        verify_local_owner(config, path)


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL boundary")
def test_windows_binding_rejects_read_access_for_other_users(tmp_path: Path) -> None:
    import win32security

    config, path = binding(tmp_path / "environment")
    original = win32security.GetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
    )
    acl = original.GetSecurityDescriptorDacl()
    acl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        0x120089,
        win32security.ConvertStringSidToSid("S-1-1-0"),
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
    with pytest.raises(ValueError, match="ADMIN-LOCAL-OWNER-ACL"):
        verify_local_owner(config, path)
