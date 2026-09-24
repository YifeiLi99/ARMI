"""Shared lab errors and local capture serialization."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LabError(RuntimeError):
    pass


def save(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
