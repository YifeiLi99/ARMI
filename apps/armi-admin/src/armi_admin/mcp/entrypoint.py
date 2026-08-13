"""Console entry for the Codex-launched local stdio MCP process."""

from __future__ import annotations

import sys

from armi_admin.application import (
    AdminConfigError,
    AdminCredentialPort,
    AdminSecretError,
    load_admin_config,
)
from armi_admin.composition import bootstrap_admin

from .server import create_admin_server


def main() -> None:
    """Load one private binding and hand stdout exclusively to MCPServer."""

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
            create_admin_server(composition.service).run("stdio")
        finally:
            composition.close()
    except (AdminConfigError, AdminSecretError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    except Exception:
        print("ADMIN-MCP-STARTUP", file=sys.stderr, flush=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()


__all__ = ("main",)
