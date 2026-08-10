"""Strict ARMI parent/runner task and result codecs."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import (
    CodexExecutionId,
    CodexModel,
    CodexReasoningEffort,
    CodexRunnerViolation,
    CodexRunResult,
    CodexRunStatus,
    CodexTaskManifest,
    CodexUsage,
)
from armi_kernel.contracts import Digest

_MAX_TASK_BYTES = 64 * 1024
_TASK_KEYS = frozenset(
    {
        "schema_version",
        "execution_id",
        "task_id",
        "effect_id",
        "source_bundle_digest",
        "source_tree_digest",
        "objective",
        "facts",
        "allowed_paths",
        "forbidden_paths",
        "validator_id",
        "deadline_seconds",
        "output_contract",
        "workspace_limit_bytes",
        "diff_limit_bytes",
        "modified_file_limit",
        "output_limit_bytes",
        "model_id",
        "reasoning_effort",
        "web_search",
    }
)
_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "execution_id",
        "status",
        "model_id",
        "sdk_version",
        "source_tree_digest",
        "final_tree_digest",
        "patch_digest",
        "usage",
        "modified_file_count",
        "validation_passed",
        "error_code",
    }
)


def decode_task(value: bytes) -> CodexTaskManifest:
    if type(value) is not bytes or not value or len(value) > _MAX_TASK_BYTES:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT")
    parsed = _json(value, "CODEX-TASK-FORMAT")
    if type(parsed) is not dict:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT")
    data = cast(dict[str, object], parsed)
    if frozenset(data) != _TASK_KEYS:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT")
    try:
        return CodexTaskManifest(
            execution_id=CodexExecutionId(UUID(str(data["execution_id"]))),
            task_id=UUID(str(data["task_id"])),
            effect_id=UUID(str(data["effect_id"])),
            source_bundle_digest=Digest.from_wire(data["source_bundle_digest"]),
            source_tree_digest=Digest.from_wire(data["source_tree_digest"]),
            objective=_string(data["objective"]),
            facts=_strings(data["facts"]),
            allowed_paths=_strings(data["allowed_paths"]),
            forbidden_paths=_strings(data["forbidden_paths"]),
            validator_id=_string(data["validator_id"]),
            deadline_seconds=_integer(data["deadline_seconds"]),
            output_contract=_string(data["output_contract"]),
            workspace_limit_bytes=_integer(data["workspace_limit_bytes"]),
            diff_limit_bytes=_integer(data["diff_limit_bytes"]),
            modified_file_limit=_integer(data["modified_file_limit"]),
            output_limit_bytes=_integer(data["output_limit_bytes"]),
            model_id=CodexModel(_string(data["model_id"])),
            reasoning_effort=CodexReasoningEffort(_string(data["reasoning_effort"])),
            web_search=_boolean(data["web_search"]),
            schema_version=_string(data["schema_version"]),
        )
    except KeyError, TypeError, ValueError:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT") from None


def encode_result(result: CodexRunResult) -> bytes:
    value = {
        "schema_version": result.schema_version,
        "execution_id": str(result.execution_id.value),
        "status": result.status.value,
        "model_id": result.model_id,
        "sdk_version": result.sdk_version,
        "source_tree_digest": result.source_tree_digest.to_wire(),
        "final_tree_digest": _digest(result.final_tree_digest),
        "patch_digest": _digest(result.patch_digest),
        "usage": (
            None
            if result.usage is None
            else {
                "input_tokens": result.usage.input_tokens,
                "cached_input_tokens": result.usage.cached_input_tokens,
                "output_tokens": result.usage.output_tokens,
            }
        ),
        "modified_file_count": result.modified_file_count,
        "validation_passed": result.validation_passed,
        "error_code": result.error_code,
    }
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def encode_task(task: CodexTaskManifest) -> bytes:
    value = {
        "schema_version": task.schema_version,
        "execution_id": str(task.execution_id.value),
        "task_id": str(task.task_id),
        "effect_id": str(task.effect_id),
        "source_bundle_digest": task.source_bundle_digest.to_wire(),
        "source_tree_digest": task.source_tree_digest.to_wire(),
        "objective": task.objective,
        "facts": list(task.facts),
        "allowed_paths": list(task.allowed_paths),
        "forbidden_paths": list(task.forbidden_paths),
        "validator_id": task.validator_id,
        "deadline_seconds": task.deadline_seconds,
        "output_contract": task.output_contract,
        "workspace_limit_bytes": task.workspace_limit_bytes,
        "diff_limit_bytes": task.diff_limit_bytes,
        "modified_file_limit": task.modified_file_limit,
        "output_limit_bytes": task.output_limit_bytes,
        "model_id": task.model_id.value,
        "reasoning_effort": task.reasoning_effort.value,
        "web_search": task.web_search,
    }
    encoded = rfc8785.dumps(cast(Any, value))
    if len(encoded) > _MAX_TASK_BYTES:
        raise CodexRunnerViolation("CODEX-TASK-FORMAT")
    return encoded + b"\n"


def decode_result(value: bytes) -> CodexRunResult:
    parsed = _json(value, "CODEX-RESULT-FORMAT")
    if type(parsed) is not dict:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    data = cast(dict[str, object], parsed)
    if frozenset(data) != _RESULT_KEYS:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    usage_value = data["usage"]
    usage: CodexUsage | None = None
    if usage_value is not None:
        if type(usage_value) is not dict:
            raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
        usage_data = cast(dict[str, object], usage_value)
        if frozenset(usage_data) != frozenset(
            {"input_tokens", "cached_input_tokens", "output_tokens"}
        ):
            raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
        usage = CodexUsage(
            _integer(usage_data["input_tokens"]),
            _integer(usage_data["cached_input_tokens"]),
            _integer(usage_data["output_tokens"]),
        )
    try:
        return CodexRunResult(
            execution_id=CodexExecutionId(UUID(_string(data["execution_id"]))),
            status=CodexRunStatus(_string(data["status"])),
            model_id=_string(data["model_id"]),
            sdk_version=_string(data["sdk_version"]),
            source_tree_digest=Digest.from_wire(data["source_tree_digest"]),
            final_tree_digest=_optional_digest(data["final_tree_digest"]),
            patch_digest=_optional_digest(data["patch_digest"]),
            usage=usage,
            modified_file_count=_integer(data["modified_file_count"]),
            validation_passed=_boolean(data["validation_passed"]),
            error_code=_optional_string(data["error_code"]),
            schema_version=_string(data["schema_version"]),
        )
    except TypeError, ValueError:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT") from None


def _json(value: bytes, code: str) -> object:
    def hook(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        return cast(
            object,
            json.loads(value.decode("utf-8", errors="strict"), object_pairs_hook=hook),
        )
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise CodexRunnerViolation(code) from None


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError
    return value


def _strings(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise TypeError
    items = cast(list[object], value)
    if any(type(item) is not str for item in items):
        raise TypeError
    return tuple(cast(list[str], items))


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _optional_digest(value: object) -> Digest | None:
    if value is None:
        return None
    return Digest.from_wire(value)


def _digest(value: Digest | None) -> str | None:
    return None if value is None else value.to_wire()


__all__ = (
    "decode_result",
    "decode_task",
    "encode_result",
    "encode_task",
)
