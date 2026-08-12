"""YAML loading for human-maintained ARMI configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_mapping(raw: bytes) -> dict[str, Any]:
    """Load a UTF-8 YAML document with PyYAML's standard safe loader."""

    try:
        text = raw.decode("utf-8", "strict")
        value = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError("invalid UTF-8 YAML configuration") from error
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("YAML root must be a text-keyed mapping")
    return value


def load_yaml_file(path: Path, *, maximum_bytes: int = 1_048_576) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum_bytes:
        raise ValueError("YAML configuration file is unavailable")
    return load_yaml_mapping(path.read_bytes())


__all__ = ("load_yaml_file", "load_yaml_mapping")
