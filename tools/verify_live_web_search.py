"""Explicit Ark built-in Web Search live gate; never part of offline quality."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import httpx
from armi_runtime.composition.web_search_verification import (
    API_BASE,
    BINDING_ID,
    MODEL,
    TOOL_DECLARATION,
    WebSearchViolation,
    metered_ark_response,
    normalize_provider_response,
)
from live_ark_credential import live_provider_meter, load_live_ark_credential
from openai import AsyncOpenAI


async def _run(root: Path, environment_root: Path) -> dict[str, object]:
    with live_provider_meter(environment_root) as meter:
        result = await _run_metered(environment_root)
        return {**result, **meter.report()}


async def _run_metered(environment_root: Path) -> dict[str, object]:
    try:
        api_key = load_live_ark_credential(environment_root).read_text()
    except Exception:
        raise WebSearchViolation("WEB-SEARCH-LIVE-CREDENTIAL") from None
    http_client = httpx.AsyncClient(trust_env=False)
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=API_BASE,
        max_retries=0,
        timeout=180,
        http_client=http_client,
    )
    started = time.perf_counter()
    try:
        response = await metered_ark_response(
            client,
            service="web_search",
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
        return {
            "status": "pass",
            "provider": "volcengine_ark",
            "model": raw.get("model"),
            "binding_id": BINDING_ID,
            "store": False,
            **evidence,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "production_model_tools": [],
            "m0_seam_web": None,
        }
    finally:
        await client.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--environment-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = asyncio.run(
            _run(args.root.resolve(), args.environment_root.resolve())
        )
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
