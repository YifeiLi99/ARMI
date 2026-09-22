"""Numeric Mind storage validation; no main-model write contract."""

import json

from ._state_storage import initial_numeric_mind_state, numeric_mind_state


def initial_mind_state() -> bytes:
    return initial_numeric_mind_state()


def validate_state(value: dict[str, object]) -> None:
    numeric_mind_state(json.dumps(value).encode("utf-8"))
