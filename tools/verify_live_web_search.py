"""Explicit Ark built-in Web Search live gate; never part of offline quality."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
from armi_runtime.adapters.model.web_search import (
    API_BASE,
    BINDING_ID,
    MODEL,
    TOOL_DECLARATION,
    WebSearchViolation,
    normalize_provider_response,
)
from openai import AsyncOpenAI

_KEY = "ARMI_SECRET_ARK_API_KEY"
_BUDGET_MICROYUAN = 2_000_000


def _read_key(path: Path) -> str:
    try:
        raw = path.read_bytes()
        value = raw.decode("utf-8", errors="strict")
    except OSError, UnicodeDecodeError:
        raise WebSearchViolation("WEB-SEARCH-LIVE-CREDENTIAL") from None
    prefix = f"{_KEY}="
    lines = value.splitlines()
    if (
        raw.startswith(b"\xef\xbb\xbf")
        or "\r" in value
        or len(lines) != 1
        or not lines[0].startswith(prefix)
    ):
        raise WebSearchViolation("WEB-SEARCH-LIVE-CREDENTIAL")
    secret = lines[0][len(prefix) :]
    if not secret or secret != secret.strip():
        raise WebSearchViolation("WEB-SEARCH-LIVE-CREDENTIAL")
    return secret


def _rates(root: Path) -> tuple[int, int]:
    try:
        manifest = json.loads(
            (
                root
                / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/"
                "model-bindings.manifest.json"
            ).read_text(encoding="utf-8")
        )
        binding = next(
            item for item in manifest["bindings"] if item["model_id"] == MODEL
        )
        input_rate = binding["input_microyuan_per_million"]
        output_rate = binding["output_microyuan_per_million"]
    except OSError, KeyError, StopIteration, TypeError, json.JSONDecodeError:
        raise WebSearchViolation("WEB-SEARCH-LIVE-COST") from None
    if not all(type(item) is int and item > 0 for item in (input_rate, output_rate)):
        raise WebSearchViolation("WEB-SEARCH-LIVE-COST")
    return cast(int, input_rate), cast(int, output_rate)


def _cost(evidence: Mapping[str, int], rates: tuple[int, int]) -> int:
    value = (
        evidence["input_tokens"] * rates[0]
        + evidence["output_tokens"] * rates[1]
        + 999_999
    ) // 1_000_000
    if value > _BUDGET_MICROYUAN:
        raise WebSearchViolation("WEB-SEARCH-LIVE-BUDGET")
    return value


async def _run(root: Path, env_file: Path) -> dict[str, object]:
    http_client = httpx.AsyncClient(trust_env=False)
    client = AsyncOpenAI(
        api_key=_read_key(env_file),
        base_url=API_BASE,
        max_retries=0,
        timeout=180,
        http_client=http_client,
    )
    started = time.perf_counter()
    try:
        response = await client.responses.create(
            model=MODEL,
            input=(
                "请使用联网搜索查找火山方舟官方 Responses API 工具调用文档。"
                "只使用公开网页。答案必须给出官方来源引用。"
            ),
            store=False,
            tools=cast(Any, [dict(TOOL_DECLARATION)]),
            max_output_tokens=1024,
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = cast(dict[str, object], response.model_dump(mode="json"))
        if not isinstance(raw.get("id"), str) or not raw["id"]:
            raise WebSearchViolation("WEB-SEARCH-LIVE-REQUEST-ID")
        _normalized, evidence = normalize_provider_response(raw)
        estimated_cost = _cost(evidence, _rates(root))
        return {
            "status": "pass",
            "provider": "volcengine_ark",
            "model": raw.get("model"),
            "binding_id": BINDING_ID,
            "store": False,
            **evidence,
            "estimated_model_cost_microyuan": estimated_cost,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "production_model_tools": [],
            "m0_seam_web": None,
        }
    finally:
        await client.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    try:
        evidence = asyncio.run(_run(args.root.resolve(), args.env_file.resolve()))
    except WebSearchViolation as exc:
        print(
            json.dumps(
                {"status": "blocked", "code": exc.code}, indent=2, sort_keys=True
            )
        )
        return 2
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
