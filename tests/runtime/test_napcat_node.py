import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import armi_local_control.napcat_node as node_module
import httpx
import psutil
import pytest
from armi_local_control.napcat_node import NapCatNode
from armi_local_control.process_identity import (
    ManagedProcessIdentity,
    ManagedProcessState,
)
from armi_local_control.runtime_errors import RuntimeViolation


@pytest.mark.parametrize(
    "name", ["../outside", "C:/outside", "file:stream", "NUL", "file. "]
)
def test_unsafe_archive_never_extracts_even_safe_earlier_entry(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("safe.txt", "safe")
        entry = zipfile.ZipInfo("entry")
        entry.filename = name
        output.writestr(entry, "bad")
    destination = tmp_path / "payload"
    destination.mkdir()
    with pytest.raises(RuntimeViolation, match="ARCHIVE-PATH"):
        node_module._extract(archive, destination)
    assert list(destination.iterdir()) == []


def test_failed_download_preserves_existing_data_and_cleans_stage(tmp_path):
    node = NapCatNode(tmp_path)
    data = tmp_path / "life.txt"
    data.write_text("life")
    with (
        patch.object(
            node,
            "_download",
            side_effect=RuntimeViolation("NAPCAT-DOWNLOAD-DIGEST", "invalid"),
        ),
        pytest.raises(RuntimeViolation, match="DOWNLOAD-DIGEST"),
    ):
        node.install("test")
    assert not node.root.exists()
    assert list(node.root.parent.iterdir()) == []
    assert data.read_text() == "life"
    assert node.status()["status"] == "failed"


def test_unrecognized_installation_is_not_overwritten(tmp_path):
    node = NapCatNode(tmp_path)
    node.root.mkdir(parents=True)
    marker = node.root / "user-file"
    marker.write_text("keep")
    with pytest.raises(RuntimeViolation, match="EXISTING-INSTALLATION"):
        node.install("test")
    assert marker.read_text() == "keep"


def test_missing_optional_component_does_not_spawn(tmp_path):
    with patch.object(node_module, "spawn_owned") as spawn:
        assert NapCatNode(tmp_path).start("test") == {"status": "not_installed"}
        assert NapCatNode(tmp_path).stop() == {"status": "stopped"}
    spawn.assert_not_called()


def test_stop_accepts_a_process_that_exits_after_its_identity_check(
    tmp_path: Path,
) -> None:
    node = NapCatNode(tmp_path)
    node.process_path.parent.mkdir(parents=True)
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        identity = ManagedProcessIdentity.capture(
            process.pid, environment_identity="test", incarnation=1
        )
        node.process_path.write_text(json.dumps(identity.to_wire()), encoding="utf-8")
        inspect = identity.inspect

        def exit_after_check() -> ManagedProcessState:
            assert inspect() == ManagedProcessState.MATCHES
            process.terminate()
            process.wait(timeout=5)
            return ManagedProcessState.MATCHES

        with (
            patch.object(node, "_identity", return_value=identity),
            patch.object(
                ManagedProcessIdentity, "inspect", side_effect=exit_after_check
            ),
        ):
            assert node.stop() == {"status": "stopped"}
        assert not node.process_path.exists()
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


@pytest.mark.parametrize("stage", ["children", "terminate"])
def test_stop_handles_parent_exit_without_skipping_known_children(
    tmp_path: Path, stage: str
) -> None:
    node = NapCatNode(tmp_path)
    node.process_path.parent.mkdir(parents=True)
    node.process_path.write_text("process marker", encoding="utf-8")
    identity = Mock(pid=1234)
    identity.inspect.return_value = ManagedProcessState.MATCHES
    parent = Mock(spec=psutil.Process)
    child = Mock(spec=psutil.Process)
    parent.children.return_value = [child]
    getattr(parent, stage).side_effect = psutil.NoSuchProcess(identity.pid)
    with (
        patch.object(node, "_identity", return_value=identity),
        patch.object(node_module.psutil, "Process", return_value=parent),
        patch.object(node_module.psutil, "wait_procs", return_value=([], [])),
    ):
        assert node.stop() == {"status": "stopped"}
    assert not node.process_path.exists()
    if stage == "terminate":
        child.terminate.assert_called_once_with()


@pytest.mark.parametrize("failure", ["access_denied", "child_alive"])
def test_stop_preserves_marker_when_shutdown_cannot_be_confirmed(
    tmp_path: Path, failure: str
) -> None:
    node = NapCatNode(tmp_path)
    node.process_path.parent.mkdir(parents=True)
    node.process_path.write_text("process marker", encoding="utf-8")
    identity = Mock(pid=1234)
    identity.inspect.return_value = ManagedProcessState.MATCHES
    parent = Mock(spec=psutil.Process)
    child = Mock(spec=psutil.Process)
    parent.children.return_value = [child]
    if failure == "access_denied":
        parent.terminate.side_effect = psutil.AccessDenied(identity.pid)
    with (
        patch.object(node, "_identity", return_value=identity),
        patch.object(node_module.psutil, "Process", return_value=parent),
        patch.object(
            node_module.psutil, "wait_procs", return_value=([parent], [child])
        ),
        pytest.raises(
            psutil.AccessDenied if failure == "access_denied" else RuntimeViolation
        ),
    ):
        node.stop()
    assert node.process_path.read_text(encoding="utf-8") == "process marker"


def test_download_rejects_content_with_wrong_digest(tmp_path):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"damaged")
        )
    )
    with (
        patch.object(node_module.httpx, "Client", return_value=client),
        patch.object(node_module, "ARCHIVE_SIZE", 7),
        pytest.raises(RuntimeViolation, match="DOWNLOAD-DIGEST"),
    ):
        NapCatNode(tmp_path)._download(tmp_path / "component.zip")


def test_download_rejects_redirect_outside_official_asset_hosts(tmp_path):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                302, headers={"location": "https://example.com/component.zip"}
            )
        )
    )
    with (
        patch.object(node_module.httpx, "Client", return_value=client),
        pytest.raises(RuntimeViolation, match="DOWNLOAD-ORIGIN"),
    ):
        NapCatNode(tmp_path)._download(tmp_path / "component.zip")
    assert not (tmp_path / "component.zip").exists()


@pytest.mark.parametrize(
    "online,uin,expected", [(False, "12345", None), (True, "12345", 12345)]
)
def test_account_discovery_authenticates_and_requires_online_login(
    tmp_path, online, uin, expected
):
    node = NapCatNode(tmp_path)
    config = node.root / "config"
    config.mkdir(parents=True)
    (config / "webui.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 3001, "token": "local-test-token"})
    )
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/api/auth/login":
            assert (
                json.loads(request.content)["hash"]
                == hashlib.sha256(b"local-test-token.napcat").hexdigest()
            )
            data = {"Credential": "test-session"}
        else:
            assert request.headers["authorization"] == "Bearer test-session"
            data = (
                {"isLogin": online}
                if request.url.path.endswith("CheckLoginStatus")
                else {"online": online, "uin": uin}
            )
        return httpx.Response(200, json={"code": 0, "data": data})

    client = httpx.Client(
        base_url="http://127.0.0.1:3001/api/", transport=httpx.MockTransport(respond)
    )
    with patch.object(node_module.httpx, "Client", return_value=client):
        assert node.login_account() == expected
    assert ("/api/QQLogin/GetQQLoginInfo" in paths) is online


@pytest.mark.parametrize("body", [b"[]", b"not json"])
@pytest.mark.parametrize(
    "route", ["auth/login", "QQLogin/CheckLoginStatus", "QQLogin/GetQQLoginInfo"]
)
def test_account_discovery_reports_invalid_webui_responses(tmp_path, route, body):
    node = NapCatNode(tmp_path)
    config = node.root / "config"
    config.mkdir(parents=True)
    (config / "webui.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 3001, "token": "local-test-token"})
    )

    def respond(request):
        if request.url.path == f"/api/{route}":
            return httpx.Response(200, content=body)
        data = {
            "/api/auth/login": {"Credential": "test-session"},
            "/api/QQLogin/CheckLoginStatus": {"isLogin": True},
            "/api/QQLogin/GetQQLoginInfo": {"online": True, "uin": "12345"},
        }[request.url.path]
        return httpx.Response(200, json={"code": 0, "data": data})

    client = httpx.Client(
        base_url="http://127.0.0.1:3001/api/", transport=httpx.MockTransport(respond)
    )
    with (
        patch.object(node_module.httpx, "Client", return_value=client),
        pytest.raises(RuntimeViolation, match="NAPCAT-LOGIN-RESPONSE"),
    ):
        node.login_account()
    assert client.is_closed
