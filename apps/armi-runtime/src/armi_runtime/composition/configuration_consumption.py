"""Versions of exact bytes read by the Runtime's configuration consumers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock

from .config_assets import runtime_config_path


class ConfigurationConsumption:
    def __init__(self, root: Path) -> None:
        self.paths = {
            runtime_config_path(
                "model-bindings.yaml", environment_root=root
            ).resolve(): "model-bindings",
            runtime_config_path(
                "web-search.yaml", environment_root=root
            ).resolve(): "web-search",
            (root / "channels/qq-napcat.yaml").resolve(): "qq",
            (root / "devices/mood-display.yaml").resolve(): "mood-display",
        }
        self._versions: dict[str, set[str]] = {}
        self._lock = Lock()

    def record(self, path: Path, raw: bytes) -> None:
        target = self.paths.get(path.resolve())
        if target is not None:
            with self._lock:
                self._versions.setdefault(target, set()).add(
                    "sha256:" + hashlib.sha256(raw).hexdigest()
                )

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {
                target: {
                    "source": str(path),
                    "versions": sorted(self._versions.get(target, ())),
                    "state": "mixed_versions"
                    if len(self._versions.get(target, ())) > 1
                    else "loaded"
                    if target in self._versions
                    else "not_loaded",
                }
                for path, target in self.paths.items()
            }


__all__ = ("ConfigurationConsumption",)
