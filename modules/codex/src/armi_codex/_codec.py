"""Strict versioned messages between ARMI and its Codex worker."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from ._runner_contract import (
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
    CodexUsage,
)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _decode(value: bytes, maximum: int) -> dict[str, Any]:
    if type(value) is not bytes or not value or len(value) > maximum:
        raise ValueError("Invalid message size")
    result = json.loads(value.decode("utf-8"), object_pairs_hook=_object)
    if type(result) is not dict:
        raise ValueError("Invalid message")
    return cast(dict[str, Any], result)


def _encode(value: CodexTaskManifest | CodexRunResult) -> bytes:
    data = asdict(value)
    data["execution_id"] = str(value.execution_id.value)
    if isinstance(value, CodexTaskManifest):
        data["task_id"] = str(value.task_id)
        data["effect_id"] = str(value.effect_id)
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def encode_task(task: CodexTaskManifest) -> bytes:
    return _encode(task)


def decode_task(value: bytes) -> CodexTaskManifest:
    try:
        data = _decode(value, 64 * 1024)
        if set(data) != set(CodexTaskManifest.__dataclass_fields__):
            raise ValueError("Invalid fields")
        data["execution_id"] = CodexExecutionId(UUID(data["execution_id"]))
        data["task_id"] = UUID(data["task_id"])
        data["effect_id"] = UUID(data["effect_id"])
        data["model_id"] = CodexModel(data["model_id"])
        data["reasoning_effort"] = CodexReasoningEffort(data["reasoning_effort"])
        return CodexTaskManifest(**data)
    except ValueError, TypeError, KeyError, AttributeError:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT") from None


def encode_result(result: CodexRunResult) -> bytes:
    return _encode(result)


def decode_result(value: bytes) -> CodexRunResult:
    try:
        data = _decode(value, 8 * 1024 * 1024)
        if set(data) != set(CodexRunResult.__dataclass_fields__):
            raise ValueError("Invalid fields")
        data["execution_id"] = CodexExecutionId(UUID(data["execution_id"]))
        data["status"] = CodexRunStatus(data["status"])
        if data["usage"] is not None:
            data["usage"] = CodexUsage(**data["usage"])
        return CodexRunResult(**data)
    except ValueError, TypeError, KeyError, AttributeError:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT") from None
