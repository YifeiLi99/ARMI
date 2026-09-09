"""Generate reviewable file evidence from the two pinned official archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from armi_local_control.semantic_recall_process import (
    CUDA_ARCHIVE,
    CUDA_ARCHIVE_SHA256,
    LLAMA_ARCHIVE,
    LLAMA_ARCHIVE_SHA256,
    SemanticRecallProcessManager,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    files = SemanticRecallProcessManager._archive_file_manifest(  # pyright: ignore[reportPrivateUsage]
        args.archive_root.resolve(strict=True)
    )
    value = {
        "schema_version": "armi.semantic-recall-files.v1",
        "archives": {
            LLAMA_ARCHIVE: LLAMA_ARCHIVE_SHA256,
            CUDA_ARCHIVE: CUDA_ARCHIVE_SHA256,
        },
        "files": [
            {"path": path, "bytes": identity[0], "sha256": identity[1]}
            for path, identity in sorted(files.items())
        ],
    }
    args.destination.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
