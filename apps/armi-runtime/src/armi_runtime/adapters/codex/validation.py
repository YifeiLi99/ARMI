"""Runner-owned validation for the only S038 conformance task."""

from __future__ import annotations

from pathlib import Path

from armi_kernel.application import CodexRunnerViolation, CodexTaskManifest

_VALIDATOR_ID = "codex.conformance.minimal-edit.v1"
_RESULT = b"ARMI_CODEX_CONFORMANCE_OK\n"


def validate_fixed_result(
    *,
    task: CodexTaskManifest,
    workspace: Path,
    changed_paths: tuple[str, ...],
) -> None:
    """Validate the only allowed conformance file independently of model claims."""

    if task.validator_id != _VALIDATOR_ID or changed_paths != ("result.txt",):
        raise CodexRunnerViolation("CODEX-VALIDATOR")
    try:
        result = (workspace / "result.txt").read_bytes()
    except OSError:
        raise CodexRunnerViolation("CODEX-VALIDATOR") from None
    if result != _RESULT:
        raise CodexRunnerViolation("CODEX-VALIDATOR")


__all__ = ("validate_fixed_result",)
