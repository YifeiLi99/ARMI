"""Structured setup CLI over transport-independent application operations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from armi_local_control import program_installation_root

from armi_admin.application.installation import (
    SetupApplication,
    SetupError,
    SetupPaths,
)
from armi_admin.application.setup_operations import SetupRequest, dispatch
from armi_admin.composition import bootstrap_setup


def application_from_arguments(argv: list[str] | None = None) -> SetupApplication:
    parser = argparse.ArgumentParser(prog="ARMI cli setup")
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--installation-root", type=Path)
    args = parser.parse_args(argv)
    installation = args.installation_root
    if installation is None:
        value = os.environ.get("ARMI_INSTALLATION_ROOT")
        if not value:
            raise SetupError("SETUP-INSTALLATION-ROOT-REQUIRED")
        installation = Path(value)
    return bootstrap_setup(
        SetupPaths(
            environment_root=args.environment_root
            or program_installation_root(installation) / "environments/active",
            installation_root=installation,
        )
    )


def main(argv: list[str] | None = None) -> int:
    application: SetupApplication | None = None
    try:
        application = application_from_arguments(argv)
        payload = sys.stdin.buffer.read(65_537)
        if len(payload) > 65_536:
            raise SetupError("SETUP-INPUT-TOO-LARGE")
        result = dispatch(application, SetupRequest.model_validate_json(payload))
    except Exception:
        result = {"status": "failed", "error_code": "SETUP-INPUT-INVALID"}
    finally:
        if application is not None:
            application.close()
    print(json.dumps(result, ensure_ascii=False))
    return (
        1 if result["status"] in {"failed", "incomplete", "reconcile_required"} else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
