"""Generate or check the committed runtime configuration governance artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from armi_runtime.composition import (
    RUNTIME_CONFIG_SCHEMA_VERSION,
    environment_override_manifest,
    schema_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = ROOT / "config/runtime.defaults.toml"
SCHEMA_PATH = ROOT / "config/runtime.schema.json"
MANIFEST_PATH = ROOT / "config/runtime-config-manifest.json"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render_manifest(schema: bytes) -> bytes:
    payload = {
        "format": "armi-runtime-config-manifest",
        "version": 1,
        "schema_version": RUNTIME_CONFIG_SCHEMA_VERSION,
        "runtime_business_contract": False,
        "defaults": {
            "path": "config/runtime.defaults.toml",
            "sha256": _digest(DEFAULTS_PATH.read_bytes()),
            "contains_secrets": False,
        },
        "schema": {
            "path": "config/runtime.schema.json",
            "sha256": _digest(schema),
        },
        "environment_overrides": environment_override_manifest(),
        "secret_locator_schemes": {
            "enabled": ["env", "file"],
            "unsupported": ["command", "os-store"],
        },
        "effective_digest": {
            "canonicalization": "RFC 8785",
            "algorithm": "sha256",
            "prefix": "sha256:",
            "includes": ["normalized effective values", "locator identities"],
            "excludes": ["secret values"],
        },
        "redaction": {
            "absolute_paths": "configured-state-only",
            "locator_targets": "scheme-and-reference-digest-only",
        },
    }
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return f"{text}\n".encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    schema = schema_bytes()
    manifest = render_manifest(schema)
    expected = {SCHEMA_PATH: schema, MANIFEST_PATH: manifest}
    if arguments.write:
        for path, content in expected.items():
            path.write_bytes(content)
        print("runtime-config-artifacts: written")
        return 0
    drifted = [
        path.relative_to(ROOT).as_posix()
        for path, content in expected.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    if drifted:
        for path in drifted:
            print(f"CON-CONFIG-SCHEMA-DRIFT: {path}")
        return 1
    print("runtime-config-artifacts: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
