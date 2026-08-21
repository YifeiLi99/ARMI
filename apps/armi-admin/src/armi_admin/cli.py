"""Explicit local CLI for destructive Admin environment operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any
from uuid import uuid7

from armi_admin.application import (
    AdminConfigError,
    AdminCredentialPort,
    AdminSecretError,
    load_admin_config,
)
from armi_admin.composition import bootstrap_admin
from armi_admin.mcp.contracts import (
    AdminToolResult,
    EnvironmentResetPreviewRequest,
    EnvironmentResetRequest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armi-admin")
    command = parser.add_subparsers(dest="command", required=True)
    reset = command.add_parser(
        "reset",
        help="archive and rebuild the configured disposable environment",
    )
    reset.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="confirm the destructive reset",
    )
    return parser


def _print_result(
    result: AdminToolResult[dict[str, Any]], *, stderr: bool = False
) -> None:
    payload = result.model_dump(mode="json")
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr if stderr else sys.stdout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Reset one explicitly configured disposable environment."""

    args = _parser().parse_args(argv)
    if args.command != "reset":  # pragma: no cover - argparse owns this invariant
        raise AssertionError(args.command)
    try:
        config, config_path = load_admin_config()
        credentials = AdminCredentialPort(
            locator=config.locator,
            migrator_locator=config.migrator_locator,
            preview_locator=config.preview_locator,
            config_root=config_path.parent,
        )
        composition = bootstrap_admin(config, credentials)
        try:
            operation = str(uuid7())
            preview = composition.service.mutate(
                "environment_reset_preview",
                EnvironmentResetPreviewRequest(
                    environment_id=config.environment_id,
                    environment_incarnation=config.environment_incarnation,
                    idempotency_key=f"cli-reset-preview-{operation}",
                    purpose="admin.environment_reset_preview",
                ),
            )
            if preview.status != "succeeded" or preview.result is None:
                _print_result(preview, stderr=True)
                return 3
            reset = composition.service.mutate(
                "environment_reset",
                EnvironmentResetRequest(
                    environment_id=config.environment_id,
                    environment_incarnation=config.environment_incarnation,
                    idempotency_key=f"cli-reset-apply-{operation}",
                    purpose="admin.environment_reset",
                    preview_token=str(preview.result["preview_token"]),
                ),
            )
            _print_result(reset, stderr=reset.status != "succeeded")
            return 0 if reset.status == "succeeded" else 3
        finally:
            composition.close()
    except (AdminConfigError, AdminSecretError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2
    except Exception:
        print("ADMIN-CLI-RESET", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("main",)
