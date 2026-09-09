"""Exact configuration versions adopted by successfully prepared consumers."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from armi_kernel import observe_configuration_reads

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
        self.paths.update(
            {
                (root / "configs/model-bindings.yaml").resolve(): "model-bindings",
                (root / "configs/web-search.yaml").resolve(): "web-search",
            }
        )
        self._consumers: dict[str, dict[str, tuple[str, str]]] = {}
        self._lock = Lock()

    @contextmanager
    def consumer(self, identity: str) -> Generator[None]:
        """Publish reads only after validation and consumer preparation succeed."""
        reads: dict[str, tuple[str, str]] = {}

        def record(path: Path, raw: bytes) -> None:
            resolved = path.resolve()
            target = self.paths.get(resolved)
            if target is not None:
                value = (str(resolved), "sha256:" + hashlib.sha256(raw).hexdigest())
                if target in reads and reads[target] != value:
                    raise ValueError("CFG-CONSUMER-INCONSISTENT")
                reads[target] = value

        with observe_configuration_reads(record):
            yield
        with self._lock:
            self._consumers[identity] = reads

    def release(self, identity: str) -> None:
        with self._lock:
            self._consumers.pop(identity, None)

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            result: dict[str, dict[str, object]] = {}
            for target in sorted(set(self.paths.values())):
                consumers = [
                    {
                        "consumer": identity,
                        "source": reads[target][0],
                        "version": reads[target][1],
                    }
                    for identity, reads in sorted(self._consumers.items())
                    if target in reads
                ]
                versions = sorted({str(item["version"]) for item in consumers})
                sources = sorted({str(item["source"]) for item in consumers})
                result[target] = {
                    "source": sources[0] if len(sources) == 1 else None,
                    "versions": versions,
                    "consumers": consumers,
                    "state": "mixed_versions"
                    if len(versions) > 1
                    else "loaded"
                    if versions
                    else "not_loaded",
                }
            return result


__all__ = ("ConfigurationConsumption",)
