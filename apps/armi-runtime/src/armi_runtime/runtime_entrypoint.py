"""Private authority worker launched by the bound local environment controller."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid7

from armi_local_control import environment_bootstrap_control_root
from armi_local_control.configuration import ConfigurationViolation
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.windows_package import package_identity
from armi_runtime_foundation import bootstrap_diagnostics

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
    instance_id = args.instance_id or uuid7()
    startup_log = bootstrap_diagnostics(
        root=environment_bootstrap_control_root(args.environment_root),
        environment_id="unbound",
        service="armi-startup",
        version=package.version if (package := package_identity()) else "source",
        instance_id=str(instance_id),
    )
    try:
        prepared = prepare_environment(
            args.environment_root,
            credential_scope=runtime_credential_scope(),
            environment=configuration_environment,
        )
    except (ConfigurationViolation, RuntimeViolation) as error:
        startup_log.write(
            "runtime.prepare.failed",
            level=logging.ERROR,
            error=error,
            result_code=error.code,
        )
        startup_log.close()
        print(
            json.dumps(
                {"status": "failed", "code": error.code, "message": error.message},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    startup_log.close()
    return run_runtime(
        prepared,
        creator_web_resources=args.creator_web_resources,
        instance_uuid=instance_id,
    )


__all__ = ("main",)


if __name__ == "__main__":
    raise SystemExit(main())
