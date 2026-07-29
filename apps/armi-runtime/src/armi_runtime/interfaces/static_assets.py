"""Verified access to the Creator resources packaged in the Runtime wheel."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import cast

_RESOURCE_PACKAGE = "armi_runtime.interfaces.creator_web_resources"


@dataclass(frozen=True, slots=True)
class AssetViolation(ValueError):
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class StaticAsset:
    content: bytes
    media_type: str
    cache_control: str


class StaticAssetStore:
    """Load only the files enumerated by the signed-off static manifest."""

    __slots__ = ("_assets",)

    def __init__(self, assets: Mapping[str, StaticAsset]) -> None:
        self._assets = MappingProxyType(dict(assets))

    @classmethod
    def load_packaged(cls) -> StaticAssetStore:
        root = files(_RESOURCE_PACKAGE)
        try:
            raw_manifest = root.joinpath("manifest.json").read_bytes()
            parsed = cast(object, json.loads(raw_manifest))
        except OSError, UnicodeDecodeError, json.JSONDecodeError:
            raise AssetViolation(
                "WEB-ASSET-MANIFEST",
                "the packaged Creator manifest is unavailable or malformed",
            ) from None
        if not isinstance(parsed, dict):
            raise AssetViolation(
                "WEB-ASSET-MANIFEST",
                "the packaged Creator manifest violates the frozen contract",
            )
        manifest = cast(dict[str, object], parsed)
        if (
            manifest.get("schema_version") != "armi.creator-static.v1"
            or manifest.get("runtime_discovery") is not False
            or manifest.get("base_path") != "/ui/"
            or manifest.get("entrypoint") != "static/index.html"
        ):
            raise AssetViolation(
                "WEB-ASSET-MANIFEST",
                "the packaged Creator manifest violates the frozen contract",
            )
        entries = manifest.get("assets")
        if not isinstance(entries, list):
            raise AssetViolation(
                "WEB-ASSET-MANIFEST",
                "the packaged Creator asset list is malformed",
            )
        assets: dict[str, StaticAsset] = {}
        for raw_entry in cast(list[object], entries):
            if not isinstance(raw_entry, dict):
                raise AssetViolation("WEB-ASSET-ENTRY", "an asset entry is malformed")
            entry = cast(dict[str, object], raw_entry)
            path = entry.get("path")
            size = entry.get("size")
            digest = entry.get("sha256")
            media_type = entry.get("media_type")
            cache_class = entry.get("cache_class")
            if (
                not isinstance(path, str)
                or not path.startswith("static/")
                or "\\" in path
                or ".." in path.split("/")
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(media_type, str)
                or cache_class
                not in {"immutable", "entrypoint-no-store", "metadata-no-store"}
                or path in assets
            ):
                raise AssetViolation("WEB-ASSET-ENTRY", "an asset entry is invalid")
            try:
                content = root.joinpath(*path.split("/")).read_bytes()
            except OSError:
                raise AssetViolation(
                    "WEB-ASSET-MISSING",
                    "a declared Creator asset is unavailable",
                ) from None
            if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                raise AssetViolation(
                    "WEB-ASSET-DIGEST",
                    "a packaged Creator asset failed integrity verification",
                )
            public_path = path.removeprefix("static/")
            cache_control = (
                "public, max-age=31536000, immutable"
                if cache_class == "immutable"
                else "no-store"
            )
            assets[public_path] = StaticAsset(
                content=content,
                media_type=media_type,
                cache_control=cache_control,
            )
        if "index.html" not in assets:
            raise AssetViolation(
                "WEB-ASSET-ENTRY",
                "the Creator entrypoint is not declared",
            )
        return cls(assets)

    def get(self, relative_path: str) -> StaticAsset | None:
        if (
            not relative_path
            or relative_path.startswith(("/", "\\"))
            or "\\" in relative_path
            or ".." in relative_path.split("/")
        ):
            return None
        return self._assets.get(relative_path)


__all__ = ("AssetViolation", "StaticAsset", "StaticAssetStore")
