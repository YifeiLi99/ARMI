"""NapCat WebUI quick-open boundary tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from armi_runtime.composition.napcat_process import NapCatProcessManager
from armi_runtime.composition.runtime_errors import RuntimeViolation


def _manager(tmp_path: Path, *, host: str = "::") -> NapCatProcessManager:
    config = tmp_path / "tools" / "napcat" / "config"
    config.mkdir(parents=True)
    (config / "webui.json").write_text(
        json.dumps(
            {
                "host": host,
                "port": 6099,
                "token": "webui-secret",
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    prepared = cast(Any, SimpleNamespace(root=tmp_path.resolve()))
    return NapCatProcessManager(prepared)


def test_open_webui_copies_token_without_putting_it_in_the_url_or_result(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    copied: list[str] = []
    opened: list[str] = []

    with (
        patch(
            "armi_runtime.composition.napcat_process._port_is_listening",
            return_value=True,
        ),
        patch(
            "armi_runtime.composition.napcat_process._copy_text_to_clipboard",
            side_effect=copied.append,
        ),
        patch(
            "armi_runtime.composition.napcat_process._open_default_browser",
            side_effect=lambda url: opened.append(url) or True,
        ),
    ):
        result = manager.open_webui()

    safe = result.safe_view()
    assert copied == ["webui-secret"]
    assert opened == ["http://127.0.0.1:6099/webui/"]
    assert safe == {
        "status": "opened",
        "webui_url": "http://127.0.0.1:6099/webui/",
        "token_delivery": "clipboard",
    }
    assert "webui-secret" not in json.dumps(safe)


def test_open_webui_rejects_a_nonlocal_configured_host(tmp_path: Path) -> None:
    manager = _manager(tmp_path, host="192.0.2.10")

    with pytest.raises(RuntimeViolation) as raised:
        manager.open_webui()

    assert raised.value.code == "CLI-QQ-WEBUI-CONFIG"
