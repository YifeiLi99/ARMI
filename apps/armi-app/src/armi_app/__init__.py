"""Product entry point; select one transport without combining its authorities."""

from __future__ import annotations

import argparse
import importlib
import os
import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="ARMI")
    parser.add_argument("mode", nargs="?", choices=("settings", "cli", "mcp"))
    parser.add_argument("scope", nargs="?", choices=("interaction", "admin", "setup"))
    if arguments[:1] in (["--help"], ["-h"]):
        parser.print_help()
        return 0
    mode = arguments.pop(0) if arguments and not arguments[0].startswith("--") else None
    if mode not in (None, "settings", "cli", "mcp"):
        parser.error("unknown mode")
    if mode in ("cli", "mcp"):
        from ._lifetime import watch_launcher

        watch_launcher()
        if not arguments:
            parser.error("choose interaction, admin, or setup")
        if arguments[0] in ("--help", "-h"):
            parser.print_help()
            return 0
        scope = arguments.pop(0)
        if scope not in ("interaction", "admin", "setup"):
            parser.error("choose interaction, admin, or setup")
        targets = {
            ("cli", "interaction"): ("armi_runtime.cli", "main"),
            ("cli", "admin"): ("armi_admin.cli", "main"),
            ("cli", "setup"): ("armi_admin.setup_cli", "main"),
            ("mcp", "interaction"): ("armi_runtime.mcp", "main"),
            ("mcp", "admin"): ("armi_admin.mcp.entrypoint", "main"),
            ("mcp", "setup"): ("armi_admin.setup_cli", "mcp_main"),
        }
        module, entry = targets[mode, scope]
    else:
        module, entry = "armi_admin.desktop", "main"
        if mode is None:
            arguments.insert(0, "--start")
    if os.environ.get("ARMI_INSTALLATION_ROOT"):
        from armi_admin.install_cli import recover_startup

        recover_startup()
    result = getattr(importlib.import_module(module), entry)(arguments)
    return result if isinstance(result, int) else 0


__all__ = ("main",)
