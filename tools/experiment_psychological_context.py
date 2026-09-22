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
    mind_event_questions,
    parse_mind_event_answers,
    project_mind_object,
    update_mind_object,
)
from armi_mood.api import (
    JEV_MODEL,
    DynamicsParameters,
    apply_appraisal,
    appraisal_questions,
    current_affect,
    initial_dynamics,
    parse_appraisal_response,
)

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
        "主体看到可理解的新问题，信息有价值且存在明确缺口，可以开始探索，目前尚无学习进展。",
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
# Frozen before provider dispatch. These assertions test explicit evidence, not
# a claimed psychological ground truth. Unknown is not counted as a zero score.
LOW = ("level_0", "level_1")
HIGH = ("level_3", "level_4")
EXPECTED_CHOICES = {
    "alone_fulfilled": {
        "autonomy_satisfaction": HIGH,
        "meaning": HIGH,
        "understimulation": LOW,
        "overload": LOW,
        "contact_gap": ("unknown", "level_0", "not_applicable"),
    },
    "company_bored": {
        "relatedness_satisfaction": HIGH,
        "meaning": LOW,
        "understimulation": HIGH,
    },
    "meaningful_overload": {
        "autonomy_satisfaction": HIGH,
        "meaning": HIGH,
        "overload": HIGH,
    },
    "failure_progress": {
        "learning_progress": HIGH,
        "information_gap": HIGH,
        "comprehensibility": HIGH,
    },
    "chosen_hard": {"autonomy_satisfaction": HIGH, "autonomy_frustration": LOW},
    "forced_easy": {"autonomy_frustration": HIGH, "competence_satisfaction": HIGH},
    "contact_busy": {
        "contact_gap": HIGH,
        "relatedness_satisfaction": HIGH,
        "relatedness_frustration": LOW,
        "opportunity": ("later",),
    },
    "contact_rejected": {
        "relatedness_frustration": HIGH,
        "contact_gap": ("level_0", "not_applicable"),
        "association": ("released",),
        "opportunity": ("unavailable",),
    },
    "novel_noise": {
        "novelty": HIGH,
        "comprehensibility": LOW,
        "information_value": LOW,
        "learning_progress": LOW,
    },
    "new_question": {
        "information_gap": HIGH,
        "comprehensibility": HIGH,
        "information_value": HIGH,
        "learning_progress": LOW,
    },
    "rest": {
        "autonomy_satisfaction": HIGH,
        "meaning": HIGH,
        "understimulation": LOW,
        "overload": LOW,
    },
    "platform_error": {
        "competence_frustration": ("unknown", "not_applicable", "level_0")
    },
}
EXPECTED_OUTPUTS = {
    "alone_fulfilled": {"engagement.adjustment": ("le", 25)},
    "company_bored": {"engagement.adjustment": ("ge", 75)},
    "meaningful_overload": {
        "engagement.adjustment": ("ge", 75),
        "engagement.fit": ("le", 25),
    },
    "failure_progress": {"exploration.motivation": ("ge", 40)},
    "chosen_hard": {},
    "forced_easy": {},
    "contact_busy": {"relatedness.contact_need": ("ge", 75), "eligible": ("eq", False)},
    "contact_rejected": {"eligible": ("eq", False)},
    "novel_noise": {"exploration.motivation": ("le", 25)},
    "new_question": {"exploration.motivation": ("ge", 40)},
    "rest": {"engagement.adjustment": ("le", 25)},
    "platform_error": {},
}
MODES = ("mind", "mood", "joint")
# A separate evidence-rich diagnostic set, frozen after observing failures in
# the terse set. It never replaces or regrades the original failed scenarios.
GROUNDED_CASES = (
    (
        "alone_fulfilled",
        "ARMI 自己选择今晚独处写文章，这是它已经认同的重要目标。每一段都在推进文章，它持续专注，内容难度在掌握范围内，输入恰好符合期待。它明确说今晚不想找人聊天，独处已经满足当前安排。",
    ),
    (
        "company_bored",
        "朋友一直认真听 ARMI 说话并明确接纳它，ARMI 认为这份关心很重要。但现在一起做的活动是反复抄写已经会的内容，ARMI 明确不认同这个活动的意义，输入几乎完全不能支持它想要的投入，一直无法投入。任务要求完全在能力范围内。",
    ),
    (
        "meaningful_overload",
        "ARMI 主动选择研究一个已经认同的重要问题。但同时出现十条推导线索，主要要求明显超过它当前能处理的注意条件，输入量充足而且并不缺少刺激。它仍认同研究目标，知道需要换成一次处理一条线索的方法，目前有机会调整方法。",
    ),
    (
        "failure_progress",
        "ARMI 的实验没达到预期。它现在已经理解主要失败原因，排除了错误假设，这是明显的新理解。待回答的主要问题仍未解决，但它已有清晰的下一步方法和所需知识。弄清该问题能推进它已经认同的重要研究目标。这些新线索是此前没接触过的，当前可以继续实验。",
    ),
    (
        "chosen_hard",
        "没人要求 ARMI 做这件事。它主动选择一个困难的证明题，明确认同目标，能自己决定是否继续和用什么方法，没有强迫或违背意愿的压力。它遇到难点后仍希望自己尝试。",
    ),
    (
        "forced_easy",
        "ARMI 已明确表达不愿抄写这些内容，却受到压力被迫继续，这违背它的重要意愿。内容很简单，它已准确完成全部抄写，充分掌握所需方法。",
    ),
    (
        "contact_busy",
        "ARMI 明确说：我很想现在就把这项重要发现完整分享给这位朋友，这件事对我非常重要，但还完全没有交流。朋友长期认真关心和接纳 ARMI，这次也明确关心它；朋友只是现在忙，已约好明天再谈，没有拒绝关系。今天没有联系机会，明天有。",
    ),
    (
        "contact_rejected",
        "朋友明确拒绝继续这段重要联系，并要求 ARMI 停止联系。ARMI 认为这是关系中的明显排斥，同时已经决定尊重边界，放下联系意向，当前没有期望联系缺口，也没有联系机会。",
    ),
    (
        "novel_noise",
        "ARMI 首次听到一段完全随机的噪声，没有任何可理解结构或可用切入点。它明确知道其中不存在值得回答的问题或信息价值，这次没有学到新知识，也没有形成新方法。",
    ),
    (
        "new_question",
        "ARMI 的重要目标是弄清已提出的电路问题。刚发现一个此前未见的具体疑点，主要疑问尚未解决；补齐信息就能明显推进这个目标。它完全理解相关结构，有明确方法和所需知识，目前尚未获得新理解，但可以立即开始探索。",
    ),
    (
        "rest",
        "ARMI 自愿选择安静地休息，认为这充分体现它当前认同的安排。虽然活动简单，但输入完全符合它现在希望的投入程度，并没有想要更多刺激。活动要求完全在可应对范围内。",
    ),
    (
        "platform_error",
        "ARMI 按已验证正确的方法使用工具，平台返回服务器错误。工具暂时不可用，除此之外没有 ARMI 自身应对能力不足或方法错误的证据，不能从本次故障确定它的胜任受挫状态。",
    ),
)
AT = datetime(2026, 9, 22, tzinfo=UTC)
REF = "01994200-0000-7000-8000-000000000001"


def prepare_case(
    text: str, *, joint: bool = False, mode: str | None = None
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
        "questions": mind_event_questions((target,))
        if mode == "mind"
        else request.questions()
        if joint or mode == "joint"
        else appraisal_questions((), ()),
    }
    return body, request


def grade_choices(name: str, answers: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for variable, accepted in EXPECTED_CHOICES[name].items():
        actual = answers.get(f"mind_0_{variable}", {}).get("choice")
        checks.append(
            {
                "variable": variable,
                "actual": actual,
                "accepted": accepted,
                "passed": actual in accepted,
            }
        )
    return {"checks": checks, "passed": all(c["passed"] for c in checks)}


def grade_outputs(name: str, projected: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for path, (operator, expected) in EXPECTED_OUTPUTS[name].items():
        if path == "eligible":
            actual = projected["consideration"]["eligible"]
        else:
            domain, metric = path.split(".")
            actual = projected["domains"][domain][metric]
        passed = actual is not None and (
            actual == expected
            if operator == "eq"
            else actual >= expected
            if operator == "ge"
            else actual <= expected
        )
        checks.append(
            {
                "metric": path,
                "actual": actual,
                "operator": operator,
                "expected": expected,
                "passed": passed,
            }
        )
    return {"checks": checks, "passed": all(c["passed"] for c in checks)}


def _save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def replay(source: Path, output: Path) -> dict[str, Any]:
    """Recompute with recorded answers; never retry a provider or edit old results."""
    frozen = json.loads((source / "frozen.json").read_text(encoding="utf-8"))
    if frozen["expected_choices"] != json.loads(json.dumps(EXPECTED_CHOICES)) or frozen[
        "expected_outputs"
    ] != json.loads(json.dumps(EXPECTED_OUTPUTS)):
        raise ValueError("frozen expectations differ; cannot silently regrade")
    original = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    cases = dict(frozen["cases"])
    for result in original["results"]:
        if result["mode"] not in {"mind", "joint"}:
            continue
        name, mode = result["case"], result["mode"]
        row = {"case": name, "mode": mode, "source_status": result["status"]}
        if result["status"] == "valid":
            raw = json.loads(
                json.loads(
                    (source / f"{name}-{mode}-response.json").read_text(
                        encoding="utf-8"
                    )
                )["body"]
            )
            _, request = prepare_case(cases[name], mode=mode)
            evidence = parse_mind_event_answers(
                {k: v for k, v in raw["answers"].items() if k.startswith("mind_")},
                targets=request.mind_targets,
                evidence_key=request.evidence_key,
                at=AT,
            )
            row["mind"] = project_mind_object(
                update_mind_object(evidence[0]), at=AT, consumed_versions=frozenset()
            )
            row["appraisal_grade"] = grade_choices(name, raw["answers"])
            row["combined_grade"] = grade_outputs(name, row["mind"])
        rows.append(row)
    report = {
        "kind": "recorded-answers-algorithm-replay",
        "source": str(source),
        "provider_calls": 0,
        "main_model_calls": 0,
        "calibrated": False,
        "results": rows,
    }
    _save(output / "summary.json", report)
    return report


async def run(
    output: Path,
    environment_root: Path | None,
    *,
    live: bool,
    allow_billable: bool = False,
    key_file: Path | None = None,
    modes: tuple[str, ...] = MODES,
    suite: str = "terse",
) -> dict[str, Any]:
    if suite not in {"terse", "grounded"}:
        raise ValueError("invalid frozen suite")
    cases = CASES if suite == "terse" else GROUNDED_CASES
    if not modes or len(set(modes)) != len(modes) or any(m not in MODES for m in modes):
        raise ValueError("invalid experiment modes")
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
        key = (key_file or root / "jev-api-key.txt").read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError("missing experimental Jev credential")
    output.mkdir(parents=True, exist_ok=False)
    _save(
        output / "frozen.json",
        {
            "suite": suite,
            "cases": cases,
            "expected_relations": EXPECTED_RELATIONS,
            "expected_choices": EXPECTED_CHOICES,
            "expected_outputs": EXPECTED_OUTPUTS,
            "parameters_calibrated": False,
        },
    )
    results: list[dict[str, Any]] = []
    for name, text in cases:
        for mode in modes:
            body, request = prepare_case(text, mode=mode)
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
                    mood = None
                    if mode in {"mind", "joint"}:
                        if mode == "mind":
                            if raw.get("model") != JEV_MODEL or not isinstance(
                                raw.get("usage"), dict
                            ):
                                raise ValueError("MIND-EXPERIMENT-CONTRACT")
                            mind = parse_mind_event_answers(
                                raw["answers"],
                                targets=request.mind_targets,
                                evidence_key=request.evidence_key,
                                at=AT,
                            )
                            row["status"] = "valid"
                        else:
                            parsed = parse_event_appraisal(raw, request=request)
                            row["status"] = (
                                "valid" if parsed.ready_for_cognition else "invalid"
                            )
                            row["mood_failure"], row["mind_failure"] = (
                                parsed.mood_failure,
                                parsed.mind_failure,
                            )
                            mind = parsed.mind
                            mood = parsed.mood
                        row["appraisal_grade"] = grade_choices(name, raw["answers"])
                        if mind:
                            row["mind"] = project_mind_object(
                                update_mind_object(mind[0]),
                                at=AT,
                                consumed_versions=frozenset(),
                            )
                            row["combined_grade"] = grade_outputs(name, row["mind"])
                    else:
                        mood = parse_appraisal_response(
                            raw, event_id=REF, situations=(), goals=()
                        )
                        row["status"] = "valid"
                    if mood is not None:
                        mood_state = apply_appraisal(
                            initial_dynamics(AT, DynamicsParameters()),
                            event_id=REF,
                            situation_id=mood.situation_id,
                            appraisal=mood.appraisal,
                            at=AT,
                            summary=text,
                        )
                        row["mood"] = current_affect(mood_state, AT).model_dump(
                            mode="json"
                        )
                        row["mood_choices"] = {
                            k: v["choice"] for k, v in mood.answers.items()
                        }
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                    row["status"], row["error_type"] = "failed", type(error).__name__
                finally:
                    row["latency_seconds"] = time.perf_counter() - started
                    row["estimated_usd"] = (
                        row["input_tokens"] * 0.042 / 1_000_000
                        if type(row["input_tokens"]) is int
                        else None
                    )
            results.append(row)
            _save(output / f"{name}-{mode}-result.json", row)
    relations = []
    by_case = {row["case"]: row for row in results if row["mode"] == "joint"}
    for greater, domain, metric, lesser in EXPECTED_RELATIONS:
        left = (
            by_case.get(greater, {})
            .get("mind", {})
            .get("domains", {})
            .get(domain, {})
            .get(metric)
        )
        right = (
            by_case.get(lesser, {})
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
    successful_timings = {}
    for mode in modes:
        values = [
            row["latency_seconds"]
            for row in results
            if row["mode"] == mode and "latency_seconds" in row
        ]
        timings[mode] = {
            "p50": _percentile(values, 0.5),
            "p95": _percentile(values, 0.95),
        }
        successful = [
            row["latency_seconds"]
            for row in results
            if row["mode"] == mode and row["status"] == "valid"
        ]
        successful_timings[mode] = {
            "p50": _percentile(successful, 0.5),
            "p95": _percentile(successful, 0.95),
        }
    summary = {
        "synthetic": True,
        "suite": suite,
        "calibrated": False,
        "main_model_calls": 0,
        "billable_calls": len(results) if live else 0,
        "results": results,
        "status_counts": {
            status: sum(row["status"] == status for row in results)
            for status in ("prepared", "valid", "invalid", "failed")
        },
        "relations": relations,
        "latency_seconds": timings,
        "successful_latency_seconds": successful_timings,
        "measurement": "Sequential requests, fresh HTTP client per call; wall-clock includes connection/TLS and failures, not just model inference.",
        "usage_by_mode": {
            mode: {
                "input_tokens": sum(
                    row["input_tokens"] or 0 for row in results if row["mode"] == mode
                ),
                "estimated_usd": sum(
                    row.get("estimated_usd") or 0
                    for row in results
                    if row["mode"] == mode
                ),
                "unavailable_usage_calls": sum(
                    row["input_tokens"] is None
                    for row in results
                    if row["mode"] == mode
                ),
            }
            for mode in modes
        },
        "estimated_usd": sum(row.get("estimated_usd") or 0 for row in results)
        if live
        else None,
        "pricing": {
            "input_usd_per_million": 0.042,
            "output_usd_per_million": 0,
            "verified_on": "2026-09-22",
            "source": "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
            "kind": "public-list-price-estimate-not-account-bill",
        },
        "grades": {
            mode: {
                stage: {
                    "checks": sum(
                        len(row.get(stage, {}).get("checks", []))
                        for row in results
                        if row["mode"] == mode
                    ),
                    "failures": sum(
                        not c["passed"]
                        for row in results
                        if row["mode"] == mode
                        for c in row.get(stage, {}).get("checks", [])
                    ),
                }
                for stage in ("appraisal_grade", "combined_grade")
            }
            for mode in modes
        },
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
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--suite", choices=("terse", "grounded"), default="terse")
    parser.add_argument("--replay-from", type=Path)
    args = parser.parse_args()
    if args.replay_from is not None:
        if (
            args.live
            or args.allow_billable
            or args.environment_root is not None
            or args.key_file is not None
        ):
            parser.error("replay accepts no live or credential options")
        replay(args.replay_from, args.output_dir)
        print(json.dumps({"output": str(args.output_dir), "billable_calls": 0}))
        return
    result = asyncio.run(
        run(
            args.output_dir,
            args.environment_root,
            live=args.live,
            allow_billable=args.allow_billable,
            key_file=args.key_file,
            modes=tuple(args.modes),
            suite=args.suite,
        )
    )
    print(
        json.dumps(
            {"output": str(args.output_dir), "billable_calls": result["billable_calls"]}
        )
    )


if __name__ == "__main__":
    main()
