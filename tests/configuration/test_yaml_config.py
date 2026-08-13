from __future__ import annotations

from pathlib import Path

import pytest
from armi_kernel import load_yaml_mapping

ROOT = Path(__file__).resolve().parents[2]


def test_yaml_config_supports_standard_yaml_features() -> None:
    assert load_yaml_mapping(
        b"""
schema_version: armi.example.v1
enabled: true
limits:
  count: 4
  ratio: 0.5
defaults: &defaults
  timeout: 30
items:
  - name: first
    tags: [\"one\", \"two\"]
    settings: *defaults
description: |
  first line
  second line
empty: {}
"""
    ) == {
        "schema_version": "armi.example.v1",
        "enabled": True,
        "limits": {"count": 4, "ratio": 0.5},
        "defaults": {"timeout": 30},
        "items": [
            {
                "name": "first",
                "tags": ["one", "two"],
                "settings": {"timeout": 30},
            }
        ],
        "description": "first line\nsecond line\n",
        "empty": {},
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"key:\tvalue\n",
        b"key: !tag value\n",
        b"key: [unterminated\n",
    ],
)
def test_yaml_config_rejects_invalid_or_unsafe_yaml(raw: bytes) -> None:
    with pytest.raises(ValueError):
        load_yaml_mapping(raw)


def test_json_object_remains_valid_yaml_input() -> None:
    assert load_yaml_mapping(
        b'{"schema_version":"armi.example.v1","enabled":true}'
    ) == {
        "schema_version": "armi.example.v1",
        "enabled": True,
    }


def test_runtime_configs_have_one_tracked_source() -> None:
    packaged = ROOT / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources"
    for name in ("runtime.yaml", "model-bindings.yaml", "web-search.yaml"):
        assert (ROOT / "configs" / name).is_file()
        assert not (packaged / name).exists()
