"""Private authority worker launched by the bound local environment controller."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from armi_local_control.configuration import ConfigurationViolation
from armi_local_control.runtime_errors import RuntimeViolation

from armi_runtime.composition.creator_session import (
    CREATOR_BEARER_LOCATOR,
    CREATOR_CURSOR_PURPOSE,
    CREATOR_VERIFY_PURPOSE,
)
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.qq_channel import (
    QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
    QQ_NAPCAT_ACCESS_TOKEN_PURPOSE,
    QQ_NAPCAT_EVENT_SECRET_LOCATOR,
    QQ_NAPCAT_EVENT_SECRET_PURPOSE,
)
from armi_runtime.composition.runtime import run_runtime


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armi-runtime-worker")
    parser.add_argument("component", choices=("runtime",))
    parser.add_argument("action", choices=("start",))
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--creator-web-resources", type=Path)
    args = parser.parse_args(argv)
    configuration_environment = dict(os.environ)
    configuration_environment.pop("ARMI_ENVIRONMENT_ROOT", None)
    try:
        prepared = prepare_environment(
            args.environment_root,
            credential_scope={
                "database.runtime": "database.runtime",
                CREATOR_VERIFY_PURPOSE: CREATOR_BEARER_LOCATOR,
                CREATOR_CURSOR_PURPOSE: CREATOR_BEARER_LOCATOR,
                "data_rights.identity_token": "data_rights.identity_token_key",
                "model.request": "model.ark_api_key",
                "speech.recognition": "speech.volc_credentials",
                "web.search": "model.ark_api_key",
                "codex.runner.auth": "codex.auth_json",
                QQ_NAPCAT_ACCESS_TOKEN_PURPOSE: QQ_NAPCAT_ACCESS_TOKEN_LOCATOR,
                QQ_NAPCAT_EVENT_SECRET_PURPOSE: QQ_NAPCAT_EVENT_SECRET_LOCATOR,
            },
            environment=configuration_environment,
        )
    except (ConfigurationViolation, RuntimeViolation) as error:
        print(
            json.dumps(
                {"status": "failed", "code": error.code, "message": error.message},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    return run_runtime(prepared, creator_web_resources=args.creator_web_resources)


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
