from types import SimpleNamespace
from typing import Any, cast

import pytest
from armi_codex._sdk_codec import normalize_sdk_turn
from armi_codex.api import CodexRunnerViolation


def test_sdk_completion_accepts_plain_text_without_usage_or_event_audit():
    result = SimpleNamespace(
        status=SimpleNamespace(value="completed"),
        error=None,
        final_response="已搜集公开资料及来源。",
        usage=None,
        items=[object()],
    )
    normalized = normalize_sdk_turn(cast(Any, result))
    assert normalized.final_response == result.final_response
    assert normalized.usage is None


@pytest.mark.parametrize(
    "status,error,text",
    [
        ("failed", object(), "partial"),
        ("interrupted", None, "partial"),
        ("completed", None, "  "),
    ],
)
def test_sdk_incomplete_or_empty_result_is_not_success(status, error, text):
    with pytest.raises(CodexRunnerViolation):
        normalize_sdk_turn(
            cast(
                Any,
                SimpleNamespace(
                    status=SimpleNamespace(value=status),
                    error=error,
                    final_response=text,
                    usage=None,
                ),
            )
        )
