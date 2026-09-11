"""Product entry point with one MCP transport and explicitly bound authorities."""

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
        if mode == "mcp":
            module, entry = "armi_app.mcp", "main"
        else:
            if not arguments:
                parser.error("choose interaction, admin, or setup")
            if arguments[0] in ("--help", "-h"):
                parser.print_help()
                return 0
            scope = arguments.pop(0)
            targets = {
                "interaction": ("armi_runtime.cli", "main"),
                "admin": ("armi_admin.cli", "main"),
                "setup": ("armi_admin.setup_cli", "main"),
            }
            if scope not in targets:
                parser.error("choose interaction, admin, or setup")
            module, entry = targets[scope]
    else:
        module, entry = "armi_admin.desktop", "main"
        if mode is None:
            arguments.insert(0, "--start")
    from armi_local_control.windows_package import initialize_process_paths

    # The transport watcher has consumed this private launcher handoff. It is
    # not a Runtime configuration override and must not reach its strict loader.
    os.environ.pop("ARMI_LAUNCHER_PID", None)
    initialize_process_paths()
    result = getattr(importlib.import_module(module), entry)(arguments)
    return result if isinstance(result, int) else 0


__all__ = ("main",)
