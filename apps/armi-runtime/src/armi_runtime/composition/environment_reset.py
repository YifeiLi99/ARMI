"""Explicit reset of one local ARMI environment to its born initial state."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from armi_kernel.application import BirthResult
from armi_local_control.configuration.paths import has_reparse_point
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.runtime_process import RuntimeProcessManager
from armi_local_control.semantic_recall_process import SemanticRecallProcessManager

from .bootstrap import execute_birth
from .database import install_operator_schema, reset_operator_schema
from .environment import PreparedEnvironment

_DATA_DIRECTORIES = ("artifacts", "codex-runner", "exports", "logs")


@dataclass(frozen=True, slots=True)
class EnvironmentResetResult:
    status: str
    cleared_targets: tuple[str, ...]
    birth: BirthResult | None

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "cleared_targets": list(self.cleared_targets),
            "birth": self.birth.safe_view() if self.birth is not None else None,
        }


def _reset_targets(prepared: PreparedEnvironment) -> tuple[Path, ...]:
    return (
        *(prepared.data_root / name for name in _DATA_DIRECTORIES),
        prepared.root / "run",
    )


def _validate_targets(prepared: PreparedEnvironment, targets: tuple[Path, ...]) -> None:
    for target in targets:
        expected_root = (
            prepared.data_root if target.parent == prepared.data_root else prepared.root
        )
        if target.parent != expected_root or has_reparse_point(
            target, root=expected_root
        ):
            raise RuntimeViolation(
                "CLI-RESET-TARGET",
                "reset target escaped its fixed environment boundary",
            )
        if target.exists() and not target.is_dir():
            raise RuntimeViolation(
                "CLI-RESET-TARGET",
                "reset target must be an ordinary directory",
            )
        if not target.exists():
            continue
        for descendant in target.rglob("*"):
            if has_reparse_point(descendant, root=target):
                raise RuntimeViolation(
                    "CLI-RESET-REPARSE",
                    "reset target contains a reparse point",
                )


def _clear_targets(targets: tuple[Path, ...]) -> tuple[str, ...]:
    cleared: list[str] = []
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        cleared.append(target.as_posix())
    return tuple(cleared)


def reset_environment(
    prepared: PreparedEnvironment, *, birth_after_reset: bool = True
) -> EnvironmentResetResult:
    """Stop local processes, replace all state, and run the fixed birth manifest."""

    process = RuntimeProcessManager(
        prepared.root,
        str(prepared.effective.config.environment.environment_id),
    )
    process.stop()
    SemanticRecallProcessManager(
        prepared.root,
        enabled=prepared.effective.config.model.semantic_recall_enabled,
    ).stop()
    targets = _reset_targets(prepared)
    _validate_targets(prepared, targets)
    reset_operator_schema(prepared)
    install_operator_schema(prepared)
    cleared = _clear_targets(targets)
    birth = execute_birth(prepared) if birth_after_reset else None
    return EnvironmentResetResult("reset", cleared, birth)


__all__ = ("EnvironmentResetResult", "reset_environment")
