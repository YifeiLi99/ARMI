"""Shared isolated task content for Creator and subject-authored delegations."""

import hashlib
import io
import zipfile
from typing import Any, cast

import rfc8785
from armi_kernel.contracts import Digest

from ._delegation_contract import CodexTaskSourceId
from ._runner_contract import CodexModel, CodexReasoningEffort


def task_bundle(task_source_id: CodexTaskSourceId) -> tuple[bytes, Digest]:
    files = {
        ".armi-task-id": f"{task_source_id.value}\n".encode(),
        "result.md": b"PENDING\n",
    }
    records = [
        {
            "path": path,
            "sha256": hashlib.sha256(value).hexdigest(),
            "bytes": len(value),
        }
        for path, value in sorted(files.items())
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, value in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, value)
    return output.getvalue(), Digest.from_bytes(rfc8785.dumps(cast(Any, records)))


def task_manifest(
    task_source_id: CodexTaskSourceId,
    objective: str,
    source_tree_digest: Digest,
    model_id: CodexModel,
    reasoning_effort: CodexReasoningEffort,
    web_search: bool,
) -> bytes:
    facts = [
        "result.md is the only task deliverable.",
        f"The stable task source identity is {task_source_id.value}.",
    ]
    if web_search:
        facts.append(
            "Codex built-in Web Search is enabled for public read-only research; "
            "credentials, login, downloads and external write actions remain forbidden."
        )
    else:
        facts.append("Codex built-in Web Search is disabled for this task.")
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.codex-task-source.v2",
                "objective": objective,
                "facts": facts,
                "allowed_paths": [],
                "forbidden_paths": [".armi-task-id"],
                "validator_id": "codex.output-artifact.v1",
                "deadline_seconds": 900,
                "source_tree_digest": source_tree_digest.value,
                "model_id": model_id.value,
                "reasoning_effort": reasoning_effort.value,
                "web_search": web_search,
            },
        )
    )
