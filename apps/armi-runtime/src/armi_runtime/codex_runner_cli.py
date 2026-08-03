"""One-shot ``armi-codex-runner`` composition entry."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from armi_kernel.application import CodexRunnerViolation

from armi_runtime.adapters.codex.codec import decode_task, encode_result
from armi_runtime.adapters.codex.custody_codec import encode_custodied_result
from armi_runtime.adapters.codex.runner import IsolatedCodexRunner
from armi_runtime.composition.configuration import ConfigurationViolation
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime_errors import RuntimeViolation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armi-codex-runner")
    parser.add_argument("--environment-root", required=True, type=Path)
    parser.add_argument("--custodied", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        task = decode_task(sys.stdin.buffer.read(64 * 1024 + 1))
        prepared = prepare_environment(
            args.environment_root,
            credential_scope={"codex.runner.auth": "codex.auth_json"},
        )
        locator = prepared.effective.config.secret_locators.get("codex.auth_json")
        if locator is None:
            raise CodexRunnerViolation("CODEX-AUTH")
        runner = IsolatedCodexRunner(
            run_root=prepared.data_root / "codex-runner",
            credential_port=prepared.credential_port,
            auth_locator=locator,
        )
        if args.custodied:
            result, artifacts = asyncio.run(runner.run_custodied(task))
            sys.stdout.buffer.write(encode_custodied_result(result, artifacts))
        else:
            result = asyncio.run(runner.run(task))
            sys.stdout.buffer.write(encode_result(result))
        return 0 if result.validation_passed else 3
    except (CodexRunnerViolation, ConfigurationViolation, RuntimeViolation) as error:
        cleanup_error = (
            error.cleanup_error_code
            if isinstance(error, CodexRunnerViolation)
            else None
        )
        sys.stderr.write(
            json.dumps(
                {
                    "status": "blocked",
                    "code": error.code,
                    "cleanup_error_code": cleanup_error,
                    "outcome_unknown": (
                        error.outcome_unknown
                        if isinstance(error, CodexRunnerViolation)
                        else False
                    ),
                    "message": "Codex runner operation failed",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 3


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
