"""NapCat process launch contract tests."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from armi_runtime.composition.napcat_process import (
    NapCatProcessManager,
    _Installation,
)


def test_quick_login_passes_account_as_launcher_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYSTEMDRIVE", "C:")
    installation = _Installation(
        root=tmp_path,
        launcher=tmp_path / "NapCatWinBootMain.exe",
        hook_library=tmp_path / "NapCatWinBootHook.dll",
        main_script=tmp_path / "napcat.mjs",
        patch_package=tmp_path / "qqnt.json",
        onebot_config=tmp_path / "config" / "onebot11_10001.json",
        qq_executable=tmp_path / "QQ.exe",
    )
    binding = SimpleNamespace(adapter=SimpleNamespace(account_id=10001))

    with patch("armi_runtime.composition.napcat_process.subprocess.Popen") as popen:
        NapCatProcessManager._launch(installation, cast(Any, binding))

    command = popen.call_args.args[0]
    assert command == (
        os.fspath(installation.launcher),
        os.fspath(installation.qq_executable),
        os.fspath(installation.hook_library),
        "10001",
    )
    assert popen.call_args.kwargs["env"]["SYSTEMDRIVE"] == "C:"
