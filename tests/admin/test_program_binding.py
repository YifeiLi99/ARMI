"""Program binding protects location, without freezing source file contents."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from armi_admin.application import admin_program_identity
from armi_admin.application.configuration import AdminConfigError, AdminExpectedIdentity


def test_source_binding_accepts_current_checkout_and_rejects_another(tmp_path):
    current = admin_program_identity()
    assert Path(current["source_root"]).is_absolute()
    AdminExpectedIdentity.model_validate(current).verify()
    with pytest.raises(AdminConfigError, match="SOURCE-ROOT"):
        AdminExpectedIdentity(source_root=str(tmp_path)).verify()
    with pytest.raises(AdminConfigError, match="SOURCE-ROOT"):
        AdminExpectedIdentity(source_root=".").verify()


def test_package_binding_rejects_unpacked_or_other_family(monkeypatch):
    import armi_local_control.windows_package as windows_package

    expected = AdminExpectedIdentity(package_family="ARMI_test")
    monkeypatch.setattr(windows_package, "package_identity", lambda: None)
    with pytest.raises(AdminConfigError, match="PACKAGE-FAMILY"):
        expected.verify()
    identity = SimpleNamespace(family="Other_test")
    monkeypatch.setattr(windows_package, "package_identity", lambda: identity)
    with pytest.raises(AdminConfigError, match="PACKAGE-FAMILY"):
        expected.verify()
    identity.family = "ARMI_test"
    expected.verify()
