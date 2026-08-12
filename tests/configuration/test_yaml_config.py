from __future__ import annotations

import pytest
from armi_kernel import load_yaml_mapping


def test_yaml_config_supports_the_project_subset() -> None:
    assert load_yaml_mapping(
        b"""
schema_version: armi.example.v1
enabled: true
limits:
  count: 4
  ratio: 0.5
items:
  - name: first
    tags: [\"one\", \"two\"]
empty: {}
"""
    ) == {
        "schema_version": "armi.example.v1",
        "enabled": True,
        "limits": {"count": 4, "ratio": 0.5},
        "items": [{"name": "first", "tags": ["one", "two"]}],
        "empty": {},
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"key: first\nkey: second\n",
        b"key:\tvalue\n",
        b"key: &anchor value\n",
        b"key: *anchor\n",
        b"key: !tag value\n",
        b" key: odd-indent\n",
        b"\xef\xbb\xbfkey: value\n",
    ],
)
def test_yaml_config_rejects_ambiguous_or_advanced_yaml(raw: bytes) -> None:
    with pytest.raises(ValueError):
        load_yaml_mapping(raw)


def test_json_object_remains_valid_yaml_input() -> None:
    assert load_yaml_mapping(b'{"schema_version":"armi.example.v1","enabled":true}') == {
        "schema_version": "armi.example.v1",
        "enabled": True,
    }
