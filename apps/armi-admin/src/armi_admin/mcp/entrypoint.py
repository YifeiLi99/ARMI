"""Console entry for the Codex-launched local stdio MCP process."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from armi_admin.application import (
    AdminConfigError,
    AdminCredentialPort,
    AdminPackageIdentityError,
    AdminSecretError,
    load_admin_config,
    verify_admin_package_set,
)
from armi_admin.composition import bootstrap_admin

from .server import create_admin_server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ARMI mcp admin")
    parser.add_argument("--config", type=str)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Load one private binding and hand stdout exclusively to MCPServer."""

    args = _parser().parse_args(argv)
    try:
        config, config_path = load_admin_config(
            {**os.environ, "ARMI_ADMIN_CONFIG": args.config} if args.config else None
        )
        verify_admin_package_set(config.expected.package_set_digest)
        credentials = AdminCredentialPort(
            locator=config.locator,
            migrator_locator=config.migrator_locator,
            preview_locator=config.preview_locator,
            authorization_locator=config.authorization_signing_key_locator,
            config_root=config_path.parent,
        )
        composition = bootstrap_admin(config, credentials)
        try:
            create_admin_server(composition.service).run("stdio")
        finally:
            composition.close()
    except (AdminConfigError, AdminPackageIdentityError, AdminSecretError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    except Exception:
        print("ADMIN-MCP-STARTUP", file=sys.stderr, flush=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()


__all__ = ("main",)
