"""YAML loading for human-maintained ARMI configuration."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import cast

import yaml

_READ_OBSERVER: ContextVar[Callable[[Path, bytes], None] | None] = ContextVar(
    "configuration_read_observer", default=None
)


@contextmanager
def observe_configuration_reads(
    observer: Callable[[Path, bytes], None],
) -> Generator[None]:
    token = _READ_OBSERVER.set(observer)
    try:
        yield
    finally:
        _READ_OBSERVER.reset(token)


def load_yaml_mapping(raw: bytes) -> dict[str, object]:
    """Load a UTF-8 YAML document with PyYAML's standard safe loader."""

    try:
        text = raw.decode("utf-8", "strict")
        value: object = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError("invalid UTF-8 YAML configuration") from error
    if type(value) is not dict:
        raise ValueError("YAML root must be a text-keyed mapping")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise ValueError("YAML root must be a text-keyed mapping")
    return cast(dict[str, object], mapping)


def read_configuration_bytes(path: Path, *, maximum_bytes: int = 1_048_576) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum_bytes:
        raise ValueError("YAML configuration file is unavailable")
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise ValueError("YAML configuration file is unavailable")
    observer = _READ_OBSERVER.get()
    if observer is not None:
        observer(path, raw)
    return raw


def load_yaml_file(path: Path, *, maximum_bytes: int = 1_048_576) -> dict[str, object]:
    return load_yaml_mapping(
        read_configuration_bytes(path, maximum_bytes=maximum_bytes)
    )


__all__ = (
    "load_yaml_file",
    "load_yaml_mapping",
    "observe_configuration_reads",
    "read_configuration_bytes",
)
