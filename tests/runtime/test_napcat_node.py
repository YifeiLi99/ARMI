import zipfile
from unittest.mock import patch

import armi_local_control.napcat_node as node_module
import httpx
import pytest
from armi_local_control.napcat_node import NapCatNode
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
