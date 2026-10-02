"""Admin credential resolution rejects empty values before any consumer runs."""

from pathlib import Path

import pytest
from armi_admin.application import AdminCredentialPort, AdminSecretError
from armi_kernel.application import CredentialLocator, CredentialPurpose


@pytest.fixture(params=["env", "file"])
def credential_source(tmp_path: Path, request):
    def resolve(value: bytes):
        if request.param == "env":
            locator = CredentialLocator.parse("env:ARMI_SECRET_ADMIN_DATABASE")
            environment = {locator.target: value.decode("ascii")}
        else:
            path = tmp_path / "admin-credential"
            path.write_bytes(value)
            locator = CredentialLocator("file", str(path))
            environment = {}
        port = AdminCredentialPort(
            locator=locator, config_root=tmp_path, environ=environment
        )
        return port.resolve(locator, CredentialPurpose("database.admin"))

    return resolve


@pytest.mark.parametrize("value", [b"", b"\n", b"\r", b"\r\n", b"\r\n\r\n"])
def test_admin_credentials_reject_empty_normalized_value(credential_source, value):
    with pytest.raises(AdminSecretError, match=r"^ADMIN-SECRET-VALUE$"):
        credential_source(value)


def test_admin_credentials_preserve_value_and_close_handle(credential_source):
    handle = credential_source(b"fixture-admin-value\r\n")
    with handle:
        assert handle.consume(bytes) == b"fixture-admin-value"
    assert handle.closed
    with pytest.raises(AdminSecretError, match=r"^ADMIN-SECRET-CLOSED$"):
        handle.consume(bytes)


def test_admin_credentials_bound_raw_environment_value(tmp_path: Path):
    locator = CredentialLocator.parse("env:ARMI_SECRET_ADMIN_DATABASE")
    port = AdminCredentialPort(
        locator=locator,
        config_root=tmp_path,
        environ={locator.target: "x" * 16384 + "\n"},
    )
    with pytest.raises(AdminSecretError, match=r"^ADMIN-SECRET-VALUE$"):
        port.resolve(locator, CredentialPurpose("database.admin"))
