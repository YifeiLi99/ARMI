"""Frozen Mood versus joint Jev probes; no subject database or main LLM calls."""

from __future__ import annotations

# ruff: noqa: RUF001 -- Frozen Chinese psychological counterexamples.
import argparse
import asyncio
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from armi_cognition.api import EventAppraisalRequest, parse_event_appraisal
from armi_mind.api import (
    GroundedObject,
    MindEvaluationTarget,
    project_mind_object,
    update_mind_object,
)
from armi_mood.api import JEV_MODEL, appraisal_questions, parse_appraisal_response

# Freeze conditions and expected directions before dispatch. Labels never enter
# the provider input. These hypotheses are not a validated five-factor scale.
CASES = (
    (
        "alone_fulfilled",
        "主体独处，自愿投入有意义的写作，需求适配且不断取得进展，没有希望联系某人的证据。",
    ),
    (
        "company_bored",
        "主体有人陪伴并被接纳，但当前重复活动缺乏意义，刺激不足，没有想联系其他人的证据。",
    ),
    (
        "meaningful_overload",
        "主体自愿选择有意义的研究，认同目标，但同时处理的要求超出了当前可应对范围。",
    ),
    (
        "failure_progress",
        "主体的实验未达目标，但已理解失败原因并学到重要新知识，问题尚未解决且可以继续探索。",
    ),
    (
        "chosen_hard",
        "主体自愿认同并选择困难任务，能自主决定方法，正在学习；困难尚未解决。",
    ),
    ("forced_easy", "主体被迫做一个容易的任务，任务违背自身意愿，却已经顺利完成。"),
    (
        "contact_busy",
        "主体明确想与朋友分享发现，对方表示关心但现在忙，要到明天才有交流机会。",
    ),
    (
        "contact_rejected",
        "主体受到对方明确排斥，对方要求停止联系，主体决定尊重边界并放下联系意向。",
    ),
    (
        "novel_noise",
        "主体听到完全不可理解的随机噪声，虽然新奇，但没有可探索的信息价值或学习进展。",
    ),
    (
        "new_question",
        "主体看到可理解的新问题，信息有价值且存在明确缺口，可以开始探索。",
    ),
    ("rest", "主体自愿选择简单安静的休息，认为这很有意义，需求与当前能力适配。"),
    (
        "platform_error",
        "主体调用工具时平台发生服务器错误，尚无主体能力不足或方法错误的证据。",
    ),
)
EXPECTED_RELATIONS = (
    ("new_question", "exploration", "motivation", "novel_noise"),
    ("company_bored", "engagement", "adjustment", "alone_fulfilled"),
    ("meaningful_overload", "engagement", "adjustment", "rest"),
)
AT = datetime(2026, 9, 22, tzinfo=UTC)
REF = "01994200-0000-7000-8000-000000000001"


def prepare_case(
    text: str, *, joint: bool
) -> tuple[dict[str, Any], EventAppraisalRequest]:
    target = MindEvaluationTarget(GroundedObject("event", REF), (REF,))
    request = EventAppraisalRequest("synthetic:frozen", REF, AT, (), (), (target,))
    body = {
        "model": JEV_MODEL,
        "state": {
            "event": {
                "id": REF,
                "source_ref": REF,
                "occurred_at": AT.isoformat(),
                "content": text,
            },
            "context": [],
            "previous_situations": [],
        },
        "questions": request.questions() if joint else appraisal_questions((), ()),
    }
    return body, request


def _save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def run(
    output: Path,
    environment_root: Path | None,
    *,
    live: bool,
    allow_billable: bool = False,
) -> dict[str, Any]:
    if live and (not allow_billable or environment_root is None):
        raise ValueError(
            "live requires isolated --environment-root and --allow-billable"
        )
    key = ""
    if live:
        assert environment_root is not None
        root = environment_root.resolve()
        # Dedicated explicit input, never installed environment configuration or
        # default credential discovery. The marker excludes ordinary ARMI roots.
        marker = json.loads((root / "jev-experiment.json").read_text(encoding="utf-8"))
        if marker != {"schema_kind": "armi.jev-experiment", "synthetic": True}:
            raise ValueError("invalid isolated experiment marker")
        key = (root / "jev-api-key.txt").read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError("missing experimental Jev credential")
    output.mkdir(parents=True, exist_ok=False)
    _save(
        output / "frozen.json",
        {
            "cases": CASES,
            "expected_relations": EXPECTED_RELATIONS,
            "parameters_calibrated": False,
        },
    )
    results: list[dict[str, Any]] = []
    for name, text in CASES:
        for mode in ("mood", "joint"):
            body, request = prepare_case(text, joint=mode == "joint")
            _save(output / f"{name}-{mode}-request.json", body)
            row: dict[str, Any] = {
                "case": name,
                "mode": mode,
                "questions": len(body["questions"]),
                "status": "prepared",
                "input_tokens": None,
                "cost": None,
            }
            if live:
                started = time.perf_counter()
                try:
                    async with httpx.AsyncClient(
                        timeout=60, follow_redirects=False, trust_env=False
                    ) as client:
                        response = await client.post(
                            "https://api.typesafe.ai/v1/systemone",
                            json=body,
                            headers={"Authorization": f"Bearer {key}"},
                        )
                    row["http_status"] = response.status_code
                    # Every returned body, including failures, remains available.
                    _save(
                        output / f"{name}-{mode}-response.json",
                        {"status": response.status_code, "body": response.text},
                    )
                    response.raise_for_status()
                    raw = response.json()
                    row["usage"] = raw.get("usage")
                    row["input_tokens"] = raw.get("usage", {}).get("input_tokens")
                    if mode == "joint":
                        parsed = parse_event_appraisal(raw, request=request)
                        row["status"] = (
                            "valid" if parsed.ready_for_cognition else "invalid"
                        )
                        row["mood_failure"], row["mind_failure"] = (
                            parsed.mood_failure,
                            parsed.mind_failure,
                        )
                        if parsed.mind:
                            row["mind"] = project_mind_object(
                                update_mind_object(parsed.mind[0]),
                                at=AT,
                                consumed_versions=frozenset(),
                            )
                    else:
                        parse_appraisal_response(
                            raw, event_id=REF, situations=(), goals=()
                        )
                        row["status"] = "valid"
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                    row["status"], row["error_type"] = "failed", type(error).__name__
                finally:
                    row["latency_seconds"] = time.perf_counter() - started
                    row["cost_status"] = "unpriced"
            results.append(row)
            _save(output / f"{name}-{mode}-result.json", row)
    relations = []
    by_case = {row["case"]: row for row in results if row["mode"] == "joint"}
    for greater, domain, metric, lesser in EXPECTED_RELATIONS:
        left = (
            by_case[greater]
            .get("mind", {})
            .get("domains", {})
            .get(domain, {})
            .get(metric)
        )
        right = (
            by_case[lesser]
            .get("mind", {})
            .get("domains", {})
            .get(domain, {})
            .get(metric)
        )
        relations.append(
            {
                "greater": greater,
                "lesser": lesser,
                "metric": metric,
                "passed": None if left is None or right is None else left > right,
            }
        )
    timings = {}
    for mode in ("mood", "joint"):
        values = [
            row["latency_seconds"]
            for row in results
            if row["mode"] == mode and "latency_seconds" in row
        ]
        timings[mode] = {
            "p50": _percentile(values, 0.5),
            "p95": _percentile(values, 0.95),
        }
    summary = {
        "synthetic": True,
        "calibrated": False,
        "main_model_calls": 0,
        "billable_calls": len(results) if live else 0,
        "results": results,
        "relations": relations,
        "latency_seconds": timings,
        "cost_status": "unpriced; reconcile provider invoice before calibration",
        "limitation": "Offline formulas and schema checks do not validate psychological appraisal reliability.",
    }
    _save(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-billable", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        run(
            args.output_dir,
            args.environment_root,
            live=args.live,
            allow_billable=args.allow_billable,
        )
    )
    print(
        json.dumps(
            {"output": str(args.output_dir), "billable_calls": result["billable_calls"]}
        )
    )


if __name__ == "__main__":
    main()
