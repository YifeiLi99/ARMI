import subprocess
import sys

import pytest


def test_private_launcher_handoff_does_not_reach_runtime_configuration(monkeypatch):
    import os
    from types import SimpleNamespace

    import armi_app

    monkeypatch.setenv("ARMI_LAUNCHER_PID", "0")
    seen = []
    original_import = armi_app.importlib.import_module

    def import_entry(name, package=None):
        if name == "armi_admin.desktop":
            return SimpleNamespace(
                main=lambda _: seen.append(os.environ.get("ARMI_LAUNCHER_PID"))
            )
        return original_import(name, package=package)

    monkeypatch.setattr(
        armi_app.importlib,
        "import_module",
        import_entry,
    )
    assert armi_app.main(["settings"]) == 0
    assert seen == [None]


@pytest.mark.parametrize("mode", ["cli", "mcp"])
@pytest.mark.parametrize("scope", ["interaction", "admin", "setup"])
def test_unified_transport_help(mode, scope):
    result = subprocess.run(
        [sys.executable, "-m", "armi_app", mode, scope, "--help"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert b"usage:" in result.stdout


@pytest.mark.parametrize("arguments", [["wrong-mode"], ["cli"], ["mcp", "wrong-scope"]])
def test_invalid_mode_rejects_without_opening_desktop(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "armi_app", *arguments],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert b"error:" in result.stderr
    assert not result.stdout
