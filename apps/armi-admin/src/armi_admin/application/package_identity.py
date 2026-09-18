"""Bind management to the installed package or an explicit source directory."""

from pathlib import Path


def admin_program_identity() -> dict[str, str]:
    return {"source_root": str(Path(__file__).resolve().parents[1])}
