"""Include the canonical Runtime YAML in both checkout and sdist wheel builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_CONFIG_NAMES = ("runtime.yaml", "model-bindings.yaml", "web-search.yaml")
_PACKAGED_DIRECTORY = Path("src/armi_runtime/composition/runtime_resources")


class CustomBuildHook(BuildHookInterface):
    """Resolve configuration from the workspace or its packaged sdist copy."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        project_root = Path(self.root).resolve()
        workspace_configs = project_root.parents[1] / "configs"
        packaged_configs = project_root / _PACKAGED_DIRECTORY
        force_include: dict[str, str] = build_data["force_include"]
        for name in _CONFIG_NAMES:
            source = workspace_configs / name
            if not source.is_file():
                source = packaged_configs / name
            if not source.is_file():
                raise FileNotFoundError(f"required Runtime configuration is missing: {name}")
            destination = (
                _PACKAGED_DIRECTORY / name
                if self.target_name == "sdist"
                else Path("armi_runtime/composition/runtime_resources") / name
            )
            force_include[str(source)] = destination.as_posix()


__all__ = ("CustomBuildHook",)
