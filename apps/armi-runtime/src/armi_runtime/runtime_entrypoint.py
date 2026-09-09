"""Private authority worker launched by the bound local environment controller."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from armi_local_control.configuration import ConfigurationViolation
from armi_local_control.runtime_errors import RuntimeViolation

from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime import run_runtime
from armi_runtime.composition.runtime_credentials import runtime_credential_scope


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armi-runtime-worker")
    parser.add_argument("component", choices=("runtime",))
    parser.add_argument("action", choices=("start",))
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--creator-web-resources", type=Path)
    parser.add_argument("--instance-id", type=UUID)
    args = parser.parse_args(argv)
    if args.instance_id is not None and args.instance_id.version != 7:
        parser.error("instance-id must be a UUIDv7")
    configuration_environment = dict(os.environ)
    configuration_environment.pop("ARMI_ENVIRONMENT_ROOT", None)
    try:
        prepared = prepare_environment(
            args.environment_root,
            credential_scope=runtime_credential_scope(),
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
    return run_runtime(
        prepared,
        creator_web_resources=args.creator_web_resources,
        instance_uuid=args.instance_id,
    )


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
