"""Verify the private installation binding before granting local owner authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from armi_local_control.configuration.paths import has_reparse_point

from .configuration import AdminConfig
from .installation import SetupIdentity


def _private_path(path: Path) -> None:
    if not path.is_absolute() or has_reparse_point(path, root=Path(path.anchor)):
        raise ValueError("ADMIN-LOCAL-OWNER-PATH")
    if os.name != "nt":
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("ADMIN-LOCAL-OWNER-ACL")
        return
    import win32api
    import win32security

    # pywin32 stubs omit PyHANDLE and nullable DACL returns at this native boundary.
    security_api = cast(Any, win32security)
    token = security_api.OpenProcessToken(win32api.GetCurrentProcess(), 8)
    try:
        user = security_api.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    trusted = {
        win32security.ConvertSidToStringSid(user),
        "S-1-5-18",
        "S-1-5-32-544",
    }
    security = security_api.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    if (
        win32security.ConvertSidToStringSid(security.GetSecurityDescriptorOwner())
        not in trusted
    ):
        raise ValueError("ADMIN-LOCAL-OWNER-ACL")
    acl = security.GetSecurityDescriptorDacl()
    if acl is None:
        raise ValueError("ADMIN-LOCAL-OWNER-ACL")
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if (
            ace[0][0] in {0, 5, 9, 11}  # ordinary, object and callback allow ACEs
            and ace[1]
            and win32security.ConvertSidToStringSid(ace[-1]) not in trusted
        ):
            raise ValueError("ADMIN-LOCAL-OWNER-ACL")


def verify_local_owner(config: AdminConfig, path: Path) -> None:
    root = config.environment_root
    state_path = root / ".setup" / "operation.json"
    if path != root / "admin.yaml" or config.operator_id != "native-local-admin":
        raise ValueError("ADMIN-LOCAL-OWNER-BINDING")
    for target in (root, root / ".setup", path, state_path, root / "secrets"):
        _private_path(target)
    state = SetupIdentity.model_validate_json(state_path.read_bytes())
    if state.environment_id != config.environment_id:
        raise ValueError("ADMIN-LOCAL-OWNER-ENVIRONMENT")


__all__ = ("verify_local_owner",)
