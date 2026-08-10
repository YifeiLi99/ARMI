"""Normalize official Codex SDK typed results without retaining hidden reasoning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import rfc8785
from armi_kernel.application import CodexRunnerViolation, CodexUsage
from openai_codex import TurnResult

_FORBIDDEN_ITEM_CODES = {
    "mcpToolCall": "CODEX-TOOL-POLICY-MCP",
    "dynamicToolCall": "CODEX-TOOL-POLICY-DYNAMIC",
    "webSearch": "CODEX-TOOL-POLICY-WEB",
    "imageView": "CODEX-TOOL-POLICY-IMAGE",
    "imageGeneration": "CODEX-TOOL-POLICY-IMAGE",
}
_MAX_ITEM_BYTES = 1024 * 1024
_MAX_TRANSCRIPT_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SdkCommandEvidence:
    command: str
    output: str
    exit_code: int
    status: str


@dataclass(frozen=True, slots=True)
class SdkTurnEvidence:
    final_response: bytes
    transcript: bytes
    usage: CodexUsage
    commands: tuple[SdkCommandEvidence, ...]


def normalize_sdk_turn(
    result: TurnResult,
    *,
    allow_web_search: bool = False,
) -> SdkTurnEvidence:
    if result.status.value != "completed" or result.error is not None:
        raise CodexRunnerViolation("CODEX-SDK-TURN")
    if type(result.final_response) is not str or not result.final_response:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    try:
        final_response = result.final_response.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT") from None
    usage = result.usage
    if usage is None:
        raise CodexRunnerViolation("CODEX-USAGE")
    total = usage.total
    normalized_usage = CodexUsage(
        total.input_tokens,
        total.cached_input_tokens,
        total.output_tokens,
    )
    records: list[dict[str, object]] = []
    commands: list[SdkCommandEvidence] = []
    for item in result.items:
        root = item.root
        item_type = getattr(root, "type", None)
        if type(item_type) is not str:
            raise CodexRunnerViolation("CODEX-SDK-EVENT")
        policy_code = _FORBIDDEN_ITEM_CODES.get(item_type)
        if item_type == "webSearch" and allow_web_search:
            policy_code = None
        if policy_code is not None:
            raise CodexRunnerViolation(policy_code)
        item_id = getattr(root, "id", None)
        if type(item_id) is not str or not item_id:
            raise CodexRunnerViolation("CODEX-SDK-EVENT")
        record: dict[str, object] = {"id": item_id, "type": item_type}
        if item_type == "commandExecution":
            command = getattr(root, "command", None)
            output = getattr(root, "aggregated_output", None)
            exit_code = getattr(root, "exit_code", None)
            status = getattr(root, "status", None)
            status_value = getattr(status, "value", status)
            if (
                type(command) is not str
                or type(output) is not str
                or type(exit_code) is not int
                or type(status_value) is not str
                or len(command.encode("utf-8")) > _MAX_ITEM_BYTES
                or len(output.encode("utf-8")) > _MAX_ITEM_BYTES
            ):
                raise CodexRunnerViolation("CODEX-SDK-EVENT")
            commands.append(
                SdkCommandEvidence(command, output, exit_code, status_value)
            )
            record.update(
                exit_code=exit_code,
                status=status_value,
            )
        else:
            dumped = root.model_dump(mode="json", by_alias=True, exclude_none=True)
            canonical = rfc8785.dumps(cast(Any, dumped))
            if len(canonical) > _MAX_ITEM_BYTES:
                raise CodexRunnerViolation("CODEX-SDK-EVENT")
        records.append(record)
    transcript = rfc8785.dumps(cast(Any, records))
    if not records or len(transcript) > _MAX_TRANSCRIPT_BYTES:
        raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
    return SdkTurnEvidence(
        final_response,
        transcript,
        normalized_usage,
        tuple(commands),
    )


def validate_final_output(
    value: bytes,
    changed_paths: tuple[str, ...],
    *,
    expected_deliverable: str | None = None,
) -> None:
    try:
        parsed = cast(object, json.loads(value.decode("utf-8")))
    except UnicodeDecodeError, ValueError:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT") from None
    if type(parsed) is not dict:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    data = cast(dict[str, object], parsed)
    expected_keys = {"summary", "changed_paths"}
    if expected_deliverable is not None:
        expected_keys.add("deliverable")
    if frozenset(data) != frozenset(expected_keys):
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    summary = data.get("summary")
    paths = data.get("changed_paths")
    deliverable = data.get("deliverable")
    if (
        type(summary) is not str
        or not summary.strip()
        or len(summary.encode("utf-8")) > 4096
        or type(paths) is not list
    ):
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    if expected_deliverable is not None and deliverable != expected_deliverable:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    path_values = cast(list[object], paths)
    if (
        any(type(path) is not str for path in path_values)
        or tuple(cast(list[str], path_values)) != changed_paths
    ):
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")


__all__ = (
    "SdkCommandEvidence",
    "SdkTurnEvidence",
    "normalize_sdk_turn",
    "validate_final_output",
)
