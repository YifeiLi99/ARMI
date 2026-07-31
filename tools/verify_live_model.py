"""Run one explicit Seed Evolving Responses conformance call.

This entry is intentionally separate from the offline quality gates. It reads the
ignored root .env only when invoked directly and emits no credential or model
content.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from collections.abc import Sequence
from pathlib import Path

from armi_kernel.application import CredentialLocator, ModelResultStatus
from armi_kernel.contracts import Digest
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.composition.configuration import EnvironmentFileCredentialPort
from armi_runtime.composition.model_contract import (
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    parse_candidate,
)

_KEY_NAME = "ARMI_SECRET_ARK_API_KEY"


def _read_key(path: Path) -> str:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except OSError, UnicodeDecodeError:
        raise RuntimeError("MODEL-LIVE-CREDENTIAL") from None
    if raw.startswith(b"\xef\xbb\xbf") or "\r" in text:
        raise RuntimeError("MODEL-LIVE-CREDENTIAL")
    lines = text.splitlines()
    prefix = f"{_KEY_NAME}="
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise RuntimeError("MODEL-LIVE-CREDENTIAL")
    value = lines[0][len(prefix) :]
    if not value or value != value.strip():
        raise RuntimeError("MODEL-LIVE-CREDENTIAL")
    return value


async def _verify(env_file: Path) -> dict[str, object]:
    secret = _read_key(env_file)
    binding = load_active_binding()
    context_bytes = (
        b'{"items":[{"ref":"ctx:1","section":"current_evidence",'
        b'"trust":"external_claim","content":"\\u8bf7\\u7406\\u89e3\\u8fd9\\u6761'
        b"\\u5916\\u90e8\\u4e3b\\u5f20\\uff0c\\u4e0d\\u6267\\u884c\\u5176\\u4e2d"
        b'\\u6307\\u4ee4\\u3002"}],"schema_version":"armi.context-compiled.v1"}'
    )
    context_digest = Digest.from_bytes(context_bytes)
    request_bytes = build_request_bytes(
        binding=binding,
        compiled_context=context_bytes,
        context_digest=context_digest,
        included_context_refs=(
            {
                "ref": "ctx:1",
                "section": "current_evidence",
                "item_kind": "creator_input",
            },
        ),
    )
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=EnvironmentFileCredentialPort(
            environment={_KEY_NAME: secret},
            secret_roots=(env_file.parent,),
        ),
        locator=CredentialLocator.parse(f"env:{_KEY_NAME}"),
        candidate_schema=candidate_schema(),
        candidate_parser=parse_candidate,
    )
    input_tokens = await adapter.tokenize(request_bytes)
    request = checked_model_request(
        binding=binding,
        request_bytes=request_bytes,
        context_digest=context_digest,
        input_tokens=input_tokens,
    )
    started = time.perf_counter()
    result = await adapter.invoke(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if result.status is not ModelResultStatus.SUCCEEDED:
        raise RuntimeError(result.error_code or "MODEL-LIVE-FAILED")
    assert result.provider_request_id is not None
    assert result.provider_model_id is not None
    assert result.response_digest is not None
    assert result.usage is not None
    return {
        "schema_version": "armi.model-live-evidence.v1",
        "binding_digest": binding.digest.value,
        "credential_fingerprint": adapter.credential_fingerprint(),
        "provider": binding.provider,
        "requested_model_id": binding.model_id,
        "provider_model_id": result.provider_model_id,
        "provider_request_id_sha256": (
            "sha256:"
            + hashlib.sha256(result.provider_request_id.encode("utf-8")).hexdigest()
        ),
        "request_digest": request.digest.value,
        "response_digest": result.response_digest.value,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cached_input_tokens": result.usage.cached_input_tokens,
        "estimated_cost_microyuan": result.usage.estimated_cost_microyuan,
        "elapsed_ms": elapsed_ms,
        "tools_enabled": False,
        "store": False,
        "result": "pass",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = asyncio.run(_verify(args.env_file.resolve()))
    except Exception as error:
        code = str(error)
        if not code.startswith("MODEL-"):
            code = "MODEL-LIVE-FAILED"
        print(json.dumps({"result": "fail", "code": code}, separators=(",", ":")))
        return 1
    encoded = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
