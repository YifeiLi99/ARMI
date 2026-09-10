import subprocess
import sys

import pytest


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
