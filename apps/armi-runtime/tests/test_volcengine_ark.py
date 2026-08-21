from __future__ import annotations

import json

import pytest
from armi_kernel.application import ModelViolation
from armi_runtime.adapters.model.volcengine_ark import (
    _provider_input,
    _strict_provider_schema,
)


@pytest.mark.parametrize(
    "schema_version",
    ("armi.creator-dialogue-input.v6",),
)
def test_provider_input_preserves_dialogue_roles(schema_version: str) -> None:
    request = json.dumps(
        {
            "schema_version": schema_version,
            "messages": [
                {"role": "system", "content": "冻结资料"},
                {"role": "user", "content": "嗨"},
            ],
        },
        ensure_ascii=False,
    ).encode()

    assert _provider_input(request) == [
        {"role": "system", "content": "冻结资料"},
        {"role": "user", "content": "嗨"},
    ]


def test_provider_input_rejects_invalid_dialogue_message() -> None:
    request = json.dumps(
        {
            "schema_version": "armi.creator-dialogue-input.v6",
            "messages": [{"role": "tool", "content": "不允许"}],
        },
        ensure_ascii=False,
    ).encode()

    with pytest.raises(ModelViolation, match="MODEL-REQUEST"):
        _provider_input(request)


def test_provider_schema_binds_context_refs_to_request() -> None:
    schema = {
        "type": "array",
        "items": {
            "type": "string",
            "pattern": r"^ctx:[1-9][0-9]{0,2}$",
            "maxLength": 7,
        },
    }

    assert _strict_provider_schema(schema, available_refs=("ctx:2", "ctx:7")) == {
        "type": "array",
        "items": {
            "type": "string",
            "enum": ["ctx:2", "ctx:7"],
        },
    }
