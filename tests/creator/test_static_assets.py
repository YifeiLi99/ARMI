from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from armi_runtime.interfaces.static_assets import AssetViolation, StaticAssetStore


def write_resources(root: Path) -> None:
    content = b"<!doctype html><title>Creator</title>"
    static = root / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_bytes(content)
    manifest = {
        "schema_version": "armi.creator-static.v1",
        "base_path": "/ui/",
        "entrypoint": "static/index.html",
        "runtime_discovery": False,
        "assets": [
            {
                "path": "static/index.html",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "media_type": "text/html",
                "cache_class": "entrypoint-no-store",
            }
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


class StaticAssetStoreTests(unittest.TestCase):
    def test_external_resource_root_loads_declared_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            write_resources(root)

            store = StaticAssetStore.load_directory(root)
            asset = store.get("index.html")

        self.assertIsNotNone(asset)
        assert asset is not None
        self.assertEqual(asset.media_type, "text/html")

    def test_external_resource_digest_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            write_resources(root)
            (root / "static/index.html").write_bytes(b"changed")

            with self.assertRaises(AssetViolation) as raised:
                StaticAssetStore.load_directory(root)

        self.assertEqual(raised.exception.code, "WEB-ASSET-DIGEST")

    def test_missing_external_resource_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = (Path(temporary) / "missing").resolve()
            with self.assertRaises(AssetViolation) as raised:
                StaticAssetStore.load_directory(missing)

        self.assertEqual(raised.exception.code, "WEB-ASSET-ROOT")


if __name__ == "__main__":
    unittest.main()
