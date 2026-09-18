import hashlib
import json

import pytest
from armi_admin.application.distribution import ProgramBundle
from armi_admin.application.updates import UpdateManifest, version_parts


def test_bundle_rejects_changed_program_and_escaped_inventory(tmp_path):
    (tmp_path / "program.txt").write_bytes(b"program")
    value = {
        "schema_version": "armi.windows-bundle.v3",
        "target": "windows-11-x64",
        "database": {
            "postgresql": "18.4",
            "vector": "0.8.6",
            "pg_trgm": "1.6",
            "baseline": "0000",
            "schema_digest": "schema-a",
            "role_policy_digest": "roles-a",
        },
        "files": {"program.txt": hashlib.sha256(b"program").hexdigest()},
    }
    value["package_id"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    (tmp_path / "bundle.json").write_text(json.dumps(value), encoding="utf-8")
    identity = ProgramBundle.read(tmp_path)
    identity.verify(tmp_path)
    (tmp_path / "program.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="INSTALLER-PACKAGE-CORRUPT"):
        identity.verify(tmp_path)
    escaping = identity.model_copy(update={"files": {"../outside": "0" * 64}})
    with pytest.raises(ValueError, match="INSTALLER-PACKAGE-BOUNDARY"):
        escaping.verify(tmp_path)


@pytest.mark.parametrize(
    "version", ["1.0", "1.2.3.65536", "1.02.3.4", "1.2.3.-1", "1.2.3.٤"]
)
def test_update_rejects_non_windows_versions(version):
    with pytest.raises(ValueError, match="UPDATE-VERSION"):
        version_parts(version)


def test_update_versions_are_compared_numerically():
    assert version_parts("1.10.0.0") > version_parts("1.9.0.0")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/YifeiLi99/ARMI/releases/download/v1/app.msix",
        "https://github.com.evil.test/YifeiLi99/ARMI/releases/download/v1/app.msix",
        "https://github.com/another/repository/releases/download/v1/app.msix",
        "https://github.com/YifeiLi99/ARMI/releases/download/v1/script.ps1",
    ],
)
def test_update_rejects_other_origins_and_scripts(url):
    with pytest.raises(ValueError, match="UPDATE-DOWNLOAD-ORIGIN"):
        UpdateManifest._origin(url)
