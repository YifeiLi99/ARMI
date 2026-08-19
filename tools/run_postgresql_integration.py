"""Run the PostgreSQL 18.4 + pgvector 0.8.6 suite in an isolated container."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from isolated_postgresql import (
    PostgreSQLLaunchError,
    PostgreSQLUnavailable,
    isolated_postgresql,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--postgresql-client-root",
        type=Path,
        default=Path(".armi-tools/installs/postgresql/18.4/pgsql"),
    )
    parser.add_argument("--s026-live-environment-root", type=Path)
    parser.add_argument("--s027-live-environment-root", type=Path)
    parser.add_argument("--s028-live-environment-root", type=Path)
    parser.add_argument("--s033-live-environment-root", type=Path)
    parser.add_argument("--test-expression")
    parser.add_argument("--creator-system-entry-point", type=Path)
    parser.add_argument("--creator-system-resources", type=Path)
    parser.add_argument("--creator-system-chromium", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    client_root = (root / args.postgresql_client_root).resolve()
    try:
        with isolated_postgresql(root) as postgresql:
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("ARMI_")
            }
            environment["S003_POSTGRESQL_CLIENT_ROOT"] = str(client_root)
            environment["S009_ADMIN_DSN"] = postgresql.admin_dsn
            if args.s026_live_environment_root is not None:
                environment["S026_LIVE_ENVIRONMENT_ROOT"] = str(
                    args.s026_live_environment_root.resolve()
                )
            if args.s027_live_environment_root is not None:
                environment["S027_LIVE_ENVIRONMENT_ROOT"] = str(
                    args.s027_live_environment_root.resolve()
                )
            if args.s028_live_environment_root is not None:
                environment["S028_LIVE_ENVIRONMENT_ROOT"] = str(
                    args.s028_live_environment_root.resolve()
                )
            if args.s033_live_environment_root is not None:
                environment["S033_LIVE_ENVIRONMENT_ROOT"] = str(
                    args.s033_live_environment_root.resolve()
                )
            creator_system = args.creator_system_entry_point is not None
            if creator_system:
                required = (
                    args.creator_system_entry_point,
                    args.creator_system_resources,
                    args.creator_system_chromium,
                )
                if any(path is None or not path.exists() for path in required):
                    print(
                        "CREATOR-SYSTEM-TOOL: wheel, resources, or Chromium is missing",
                        file=sys.stderr,
                    )
                    return 2
                environment["ARMI_CREATOR_SYSTEM_ENTRY_POINT"] = str(
                    args.creator_system_entry_point.resolve()
                )
                environment["ARMI_CREATOR_SYSTEM_RESOURCES"] = str(
                    args.creator_system_resources.resolve()
                )
                environment["ARMI_CREATOR_SYSTEM_CHROMIUM"] = str(
                    args.creator_system_chromium.resolve()
                )
            pytest_command = [sys.executable, "-m", "pytest", "tests/postgresql", "-q"]
            test_expression = args.test_expression
            if args.s026_live_environment_root is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s027_live_environment_root is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s028_live_environment_root is not None and test_expression is None:
                test_expression = "t03_subject_commit"
            if args.s033_live_environment_root is not None and test_expression is None:
                test_expression = "web_observation_admission"
            if creator_system and test_expression is None:
                test_expression = "creator_system_browser"
            if creator_system:
                pytest_command.extend(("-m", "creator_system"))
            else:
                pytest_command.extend(("-m", "not creator_system"))
            if test_expression is not None:
                pytest_command.extend(("-k", test_expression))
            completed = subprocess.run(
                pytest_command,
                cwd=root,
                env=environment,
                check=False,
            )
            return completed.returncode
    except PostgreSQLUnavailable as error:
        print(f"{error}: isolated Docker PostgreSQL is unavailable", file=sys.stderr)
        return 2
    except PostgreSQLLaunchError as error:
        print(f"{error}: isolated Docker PostgreSQL failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
