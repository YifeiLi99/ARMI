"""Static runner-owned validators for isolated Codex task results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from armi_kernel.application import CodexRunnerViolation, CodexTaskManifest

_CONFORMANCE_VALIDATOR = "codex.conformance.minimal-edit.v1"
_OUTPUT_VALIDATOR = "codex.output-artifact.v1"
_RESULT = b"ARMI_CODEX_CONFORMANCE_OK\n"
_MAX_DELIVERABLE_BYTES = 1024 * 1024


def materialize_output_artifact(
    *, task: CodexTaskManifest, workspace: Path, final_response: bytes
) -> None:
    """Persist a declared deliverable; the model need not duplicate this via shell."""

    if task.validator_id != _OUTPUT_VALIDATOR:
        return
    try:
        parsed = cast(object, json.loads(final_response.decode("utf-8", errors="strict")))
        if type(parsed) is not dict:
            raise ValueError
        value = cast(dict[str, object], parsed).get("deliverable")
        if (
            type(value) is not str
            or not value.strip()
            or "\x00" in value
            or len(value.encode("utf-8")) > _MAX_DELIVERABLE_BYTES
        ):
            raise ValueError
        (workspace / "result.md").write_text(
            value, encoding="utf-8", errors="strict", newline=""
        )
    except OSError, UnicodeDecodeError, ValueError:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT") from None


def validate_fixed_result(
    *,
    task: CodexTaskManifest,
    workspace: Path,
    changed_paths: tuple[str, ...],
) -> str | None:
    """Dispatch only to statically registered independent validators."""

    if task.validator_id == _CONFORMANCE_VALIDATOR:
        _validate_conformance(workspace, changed_paths)
        return None
    if task.validator_id == _OUTPUT_VALIDATOR:
        return _validate_output_artifact(workspace, changed_paths)
    raise CodexRunnerViolation("CODEX-VALIDATOR")


def _validate_conformance(workspace: Path, changed_paths: tuple[str, ...]) -> None:
    if changed_paths != ("result.txt",):
        raise CodexRunnerViolation("CODEX-VALIDATOR")
    try:
        result = (workspace / "result.txt").read_bytes()
    except OSError:
        raise CodexRunnerViolation("CODEX-VALIDATOR") from None
    if result != _RESULT:
        raise CodexRunnerViolation("CODEX-VALIDATOR")


def _validate_output_artifact(workspace: Path, changed_paths: tuple[str, ...]) -> str:
    if changed_paths != ("result.md",):
        raise CodexRunnerViolation("CODEX-VALIDATOR")
    try:
        value = (workspace / "result.md").read_bytes()
        text = value.decode("utf-8", errors="strict")
    except OSError, UnicodeDecodeError:
        raise CodexRunnerViolation("CODEX-VALIDATOR") from None
    if (
        not value
        or len(value) > _MAX_DELIVERABLE_BYTES
        or "\x00" in text
        or not text.strip()
        or value == b"PENDING\n"
    ):
        raise CodexRunnerViolation("CODEX-VALIDATOR")
    return text


__all__ = ("materialize_output_artifact", "validate_fixed_result")
