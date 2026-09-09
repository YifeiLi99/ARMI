"""Locate the single source of human-maintained Runtime configuration."""

from __future__ import annotations

from pathlib import Path

from armi_runtime.application.model_manifest import load_model_manifest

_CONFIG_NAMES = frozenset({"runtime.yaml", "model-bindings.yaml", "web-search.yaml"})


def runtime_config_path(name: str, *, environment_root: Path | None = None) -> Path:
    """Use root configs in a checkout and packaged copies in an installed wheel."""

    if name not in _CONFIG_NAMES:
        raise ValueError("unknown Runtime configuration")
    if environment_root is not None and name != "runtime.yaml":
        from armi_local_control.configuration.paths import has_reparse_point

        override = environment_root / "configs" / name
        if override.exists():
            if not override.is_file() or has_reparse_point(
                override, root=environment_root
            ):
                raise ValueError("CFG-OVERRIDE-PATH")
            return _validated_path(name, override)
    workspace_config = Path(__file__).resolve().parents[5] / "configs" / name
    if workspace_config.is_file():
        return _validated_path(name, workspace_config)
    packaged_config = Path(__file__).parent / "runtime_resources" / name
    if packaged_config.is_file():
        return _validated_path(name, packaged_config)
    raise FileNotFoundError(name)


def _validated_path(name: str, path: Path) -> Path:
    if name == "model-bindings.yaml":
        load_model_manifest(path)
    return path


__all__ = ("runtime_config_path",)
