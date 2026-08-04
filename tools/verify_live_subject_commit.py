"""Run the single explicit S026 model-to-T-03 live gate.

The invoked PostgreSQL test owns an isolated database and data root. This wrapper
never reads or prints the credential; it only passes the ignored env-file path to
the child process that performs one Seed Evolving Responses invocation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tool-root", type=Path, default=Path(".armi-tools"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    environment = dict(os.environ)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(name, None)
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "tools/run_postgresql_integration.py"),
            "--root",
            str(root),
            "--tool-root",
            str(args.tool_root),
            "--s026-live-env-file",
            str(args.env_file.resolve()),
        ],
        cwd=root,
        check=False,
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
