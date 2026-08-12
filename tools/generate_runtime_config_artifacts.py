"""Generate or verify packaged Runtime configuration resources."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_TARGET = Path("apps/armi-runtime/src/armi_runtime/composition/runtime_resources")
_CONFIG = {
    "runtime.yaml": Path("configs/runtime.yaml"),
    "model-bindings.yaml": Path("configs/model-bindings.yaml"),
    "web-search.yaml": Path("configs/web-search.yaml"),
}


def _generate(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for target_name, source_relative in _CONFIG.items():
        (output / target_name).write_bytes((root / source_relative).read_bytes())


def _files(root: Path) -> dict[str, bytes]:
    return {
        name: (root / name).read_bytes()
        for name in _CONFIG
        if (root / name).is_file()
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="runtime-config-",
            dir=temporary_root,
        ) as temporary:
            generated = Path(temporary)
            _generate(root, generated)
            target = root / _TARGET
            if args.write:
                target.mkdir(parents=True, exist_ok=True)
                for name, value in _files(generated).items():
                    (target / name).write_bytes(value)
            elif _files(generated) != _files(target):
                print("CFG-RESOURCE-DRIFT: packaged configs drifted", file=sys.stderr)
                return 1
        print("runtime-config: written" if args.write else "runtime-config: verified")
        return 0
    except OSError:
        print("CFG-RESOURCE-MISSING: a config input is unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
