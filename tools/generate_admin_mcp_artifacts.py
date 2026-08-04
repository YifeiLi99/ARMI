"""Keep the public Admin configuration schema in sync with its Pydantic model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from armi_admin.application import AdminConfig

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "apps/armi-admin/src/armi_admin/mcp/resources/admin-config.schema.json"


def _expected() -> bytes:
    value = AdminConfig.model_json_schema(mode="validation")
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = _expected()
    if args.write:
        TARGET.write_bytes(expected)
    elif not TARGET.is_file() or TARGET.read_bytes() != expected:
        raise SystemExit("ADMIN-CONFIG-SCHEMA-DRIFT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
