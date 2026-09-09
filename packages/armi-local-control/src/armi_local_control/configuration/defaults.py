"""Locate the fixed Runtime configuration resource without importing Runtime."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


def runtime_defaults_file() -> Path:
    checkout = Path(__file__).resolve().parents[5] / "configs/runtime.yaml"
    if checkout.is_file():
        return checkout
    try:
        resource = Path(
            str(
                distribution("armi-runtime").locate_file(
                    "armi_runtime/composition/runtime_resources/runtime.yaml"
                )
            )
        )
    except PackageNotFoundError:
        raise FileNotFoundError("LOCAL-RUNTIME-NOT-INSTALLED") from None
    if not resource.is_file():
        raise FileNotFoundError("LOCAL-RUNTIME-DEFAULTS-MISSING")
    return resource


__all__ = ("runtime_defaults_file",)
