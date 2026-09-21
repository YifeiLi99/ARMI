"""Compare typed Mood appraisals using synthetic scenes and the real Mood policy."""

from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese semantic instructions and rubrics.
import argparse
import asyncio
import json
import math
import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from armi_kernel import load_yaml_file
from armi_mood.api import (
    MOOD_APPRAISAL_INSTRUCTIONS,
    MoodSemanticAppraisalCommand,
    preview_appraisal,
    semantic_appraisal_from_command,
)
from experiment_jev import load_key, save
from experiment_jev_memory import ProbeError, cost_bounds, deepseek_key

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_ID = "00000000-0000-7000-8000-000000000001"
PROVIDERS = ("jev", "deepseek")

# Each option maps directly to an existing Mood enum, except absent/skip routing.
FIELDS = {
    "event_phase": ("事件目前所处阶段", "anticipated ongoing realized averted"),
    "expectedness": (
        "意外程度",
        "expected somewhat_unexpected expectation_broken unknown",
    ),
    "outcome_certainty": (
        "结果发生的确定程度，已确定发生是settled",
        "open uncertain likely settled unknown",
    ),
    "intrinsic_quality": (
        "体验本身的愉快或排斥，不等于目标受挫",
        "strongly_aversive unpleasant neutral pleasant strongly_pleasant mixed unknown",
    ),
    "self_involvement": (
        "对自我身份的卷入，普通话题不等于身份层面",
        "none limited important identity_level unknown",
    ),
    "engagement": (
        "有意义投入是否满足；自愿休息不等于投入不足",
        "satisfying understimulated overloaded not_applicable unknown",
    ),
    "demand_urgency": ("必须应对的紧迫程度", "none can_wait soon immediate unknown"),
    "demand_effort": ("需要付出的努力", "none light substantial extreme unknown"),
    "causality_agency": (
        "造成所评价事件后果的责任来源",
        "self other shared circumstance unknown",
    ),
    "causality_intentionality": (
        "是否有意造成被评价后果，而非动作是否有意识",
        "accidental unclear deliberate not_applicable unknown",
    ),
    "coping_response_access": (
        "应对途径是否可直接采用",
        "none indirect direct resolved unknown",
    ),
    "coping_power_balance": (
        "自身应对能力相对处境的力量",
        "overmatched limited balanced advantaged unknown",
    ),
    "coping_adjustment": (
        "调整和适应的难度",
        "blocked difficult manageable easy unknown",
    ),
    "norm_compatibility": (
        "有依据的社会规范是否受到违反；没有相关规范是not_applicable",
        "violation tension aligned mixed not_applicable unknown",
    ),
    "self_standard": (
        "个人准则兼容性与自我否定范围的组合。action仅涉及行为，global需要明确整体自我否定。",
        "violation_action violation_global tension_action tension_global mixed_action mixed_global aligned not_applicable unknown",
    ),
}
for _target, _description in (
    ("self_goal", "主体自身目标；不能把他人的目标直接算作自身目标"),
    ("relationship", "信任、亲近与关系延续；暂时不能交流不自动等于关系受损"),
    ("social_order", "社会秩序和规范目标"),
):
    FIELDS[f"{_target}_significance"] = (
        f"{_description}的重要性。absent表示当前事件不涉及该目标；peripheral为边缘小事，direct为直接相关，core为已有核心目标，unknown为信息不足。",
        "absent peripheral direct core unknown",
    )
    FIELDS[f"{_target}_direction"] = (
        f"{_description}受影响的方向。major_setback重大损失，setback受挫，unchanged未变，progress进展，fulfilled达成；无该目标时选unknown。",
        "major_setback setback unchanged progress fulfilled mixed unknown",
    )
FIELDS["transition"] = (
    "选择是否提交评价及事件轨迹；skip不提交。new仅用于新事件，其余组合为既有事件的更新方式与相比此前的变化。没有既有episode不能选择既有事件更新。仅再想一遍不能new或reinforce。",
    "new skip "
    + " ".join(
        f"{transition}_{change}"
        for transition in ("reinforce", "reappraise", "resolve")
        for change in ("improved", "unchanged", "worsened", "mixed", "unknown")
    ),
)


def request_body(case: dict, repetition: int, seed: int) -> dict:
    rng = random.Random(f"{seed}:{case['id']}:{repetition}")
    questions = {}
    for name, (description, values) in FIELDS.items():
        options = values.split()
        rng.shuffle(options)
        questions[name] = {
            "type": "choice",
            "instructions": "遵循 state.armi_mood_rules 和 state.output_contract，评价 state.scene 对主体的意义。"
            + description,
            "criteria": dict.fromkeys(options),
        }
    return {
        "model": "jev-1.13.0",
        "state": {
            "armi_mood_rules": MOOD_APPRAISAL_INSTRUCTIONS,
            "scene": case["scene"],
            "existing_episode": case["existing_episode"],
            "scope": "处境已由宿主分段；只评价这一事件。未提供的事实不可自行编造，缺信息用unknown。",
            "output_contract": "transition不是skip时，三个target_significance至少一个不能是absent，否则无法构成Mood评价。三个目标均不涉及且不需评价时应选skip。不能为凑合同虚构目标。absent与unknown不同：前者明确不涉及，后者涉及但重要性信息不足。",
        },
        "questions": questions,
    }


def parse_choices(raw: dict, provider: str) -> tuple[dict, dict]:
    confidence = {}
    if provider == "jev":
        if raw["model"] != "jev-1.13.0" or set(raw["answers"]) != set(FIELDS):
            raise ProbeError("INVALID-JEV-CONTRACT")
        chosen = {}
        for name, answer in raw["answers"].items():
            options = set(FIELDS[name][1].split())
            probabilities = answer["probabilities"]
            if answer["type"] != "choice" or set(probabilities) != options:
                raise ProbeError("INVALID-JEV-OPTIONS")
            values = list(probabilities.values())
            if any(
                type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                for p in values
            ):
                raise ProbeError("INVALID-JEV-PROBABILITIES")
            # Live API rounds each probability to two decimals; do not normalize
            # the response or reject a valid rounded distribution such as 0.99.
            if not math.isclose(sum(values), 1, abs_tol=0.005 * len(values) + 1e-9):
                raise ProbeError("INVALID-JEV-PROBABILITY-SUM")
            chosen[name] = answer["choice"]
            confidence[name] = answer["confidence"]
    else:
        completion = raw["choices"][0]
        if completion["finish_reason"] != "stop":
            raise ProbeError("INCOMPLETE-RESPONSE")
        chosen = json.loads(completion["message"]["content"])
    if not isinstance(chosen, dict) or set(chosen) != set(FIELDS):
        raise ProbeError("INVALID-CHOICE-KEYS")
    if any(
        not isinstance(value, str) or value not in FIELDS[name][1].split()
        for name, value in chosen.items()
    ):
        raise ProbeError("INVALID-CHOICE")
    return chosen, confidence


def derive(choices: dict, case: dict) -> dict:
    if choices["transition"] == "skip":
        return {"status": "no_appraisal", "derived": None}
    concerns = [
        {
            "target": target,
            "significance": choices[f"{target}_significance"],
            "direction": choices[f"{target}_direction"],
        }
        for target in ("self_goal", "relationship", "social_order")
        if choices[f"{target}_significance"] != "absent"
    ]
    if not concerns:
        raise ProbeError("APPRAISAL-WITHOUT-CONCERN")
    transition, _, change = choices["transition"].partition("_")
    if transition != "new" and not case["existing_episode"]:
        raise ProbeError("EXISTING-EPISODE-MISSING")
    self_compatibility, _, self_scope = (
        choices["self_standard"].rpartition("_")
        if choices["self_standard"].endswith(("_action", "_global"))
        else (choices["self_standard"], "", "")
    )
    self_evaluation = {"compatibility": self_compatibility}
    if self_scope:
        self_evaluation["scope"] = self_scope
    appraisal = {
        key: choices[key]
        for key in (
            "expectedness",
            "outcome_certainty",
            "intrinsic_quality",
            "self_involvement",
            "engagement",
        )
    }
    appraisal["concerns"] = concerns
    for group, fields in (
        ("demand", ("urgency", "effort")),
        ("causality", ("agency", "intentionality")),
        ("coping", ("response_access", "power_balance", "adjustment")),
    ):
        appraisal[group] = {field: choices[f"{group}_{field}"] for field in fields}
    appraisal["standards"] = {
        "self_evaluation": self_evaluation,
        "norm_compatibility": choices["norm_compatibility"],
    }
    command = MoodSemanticAppraisalCommand.model_validate_json(
        json.dumps(
            {
                "schema_kind": "armi.mood-appraisal",
                "transition": transition,
                "previous_episode_id": None if transition == "new" else PREVIOUS_ID,
                "change_from_previous": None if transition == "new" else change,
                "event_phase": choices["event_phase"],
                "gist": "合成处境评价",
                "appraisal": appraisal,
            }
        )
    )
    event = semantic_appraisal_from_command(command)
    if transition != "new":
        # Public preview cannot reconstruct previous affect; do not fake a trajectory.
        return {
            "status": "existing_semantics_only",
            "command": command.model_dump(mode="json"),
            "derived": None,
        }
    return {
        "status": "derived",
        "command": command.model_dump(mode="json"),
        "derived": preview_appraisal(event),
    }


def grade(choices: dict, case: dict, mood: dict | None) -> dict:
    checks = {
        field: choices[field] in allowed for field, allowed in case["expected"].items()
    }
    for target, forbidden in case.get("forbidden_impacts", {}).items():
        checks[f"{target}_no_false_damage"] = (
            choices[f"{target}_significance"] == "absent"
            or choices[f"{target}_direction"] not in forbidden
        )
    semantic = {
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "all_passed": all(checks.values()),
    }
    if case["existing_episode"] or mood is None:
        return {"semantic": semantic, "emotion": None}
    derived = mood["derived"]
    families = (
        set()
        if derived is None
        else {item["component"]["family"] for item in derived["components"]}
    )
    missing = set(case["required_emotions"]) - families
    unexpected = set(case["forbidden_emotions"]) & families
    return {
        "semantic": semantic,
        "emotion": {
            "passed": not missing and not unexpected,
            "missing": sorted(missing),
            "forbidden_present": sorted(unexpected),
            "families": sorted(families),
        },
    }


def summarize(rows: list[dict], config: dict) -> dict:
    result = {}
    for provider in PROVIDERS:
        group = [row for row in rows if row["provider"] == provider]
        parsed = [row for row in group if "grade" in row]
        good = [row for row in group if row["status"] == "succeeded"]
        grades = [row["grade"]["semantic"] for row in parsed]
        emotion = [
            row["grade"]["emotion"]
            for row in good
            if row["grade"]["emotion"] is not None
        ]
        costs = [cost_bounds(provider, row["usage"]) for row in group if "usage" in row]
        pairs = []
        for low, high in config["intensity_pairs"]:
            for rep in range(config["repetitions"]):
                pair = {
                    row["case"]: row
                    for row in good
                    if row["case"] in (low, high)
                    and row["rep"] == rep
                    and row["mood"]["derived"] is not None
                }
                if len(pair) == 2:
                    low_value = pair[low]["mood"]["derived"]["core"]["intensity"]
                    high_value = pair[high]["mood"]["derived"]["core"]["intensity"]
                    pairs.append(
                        {
                            "low": low,
                            "high": high,
                            "rep": rep,
                            "values": [low_value, high_value],
                            "ordered": high_value > low_value,
                        }
                    )
        result[provider] = {
            "attempted": len(group),
            "contract_valid": len(good),
            "semantic_checks_passed": sum(g["passed"] for g in grades),
            "semantic_checks_total": sum(g["total"] for g in grades),
            "all_critical_checks_passed": sum(g["all_passed"] for g in grades),
            "graded_rows": len(parsed),
            "emotion_checks_passed": sum(g["passed"] for g in emotion),
            "emotion_checked_rows": len(emotion),
            "latency_median_ms": statistics.median(row["latency_ms"] for row in good)
            if good
            else None,
            "estimated_usd_off_peak": sum(v[0] for v in costs),
            "estimated_usd_peak": sum(v[1] for v in costs),
            "unconfirmed_usage_calls": sum("usage" not in row for row in group),
            "intensity_pairs": pairs,
        }
    return result


async def run(
    config: dict, output: Path, environment: Path | None, *, live: bool
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    save(output / "config.json", config)
    jobs = []
    for rep in range(config["repetitions"]):
        for case in config["cases"]:
            body = request_body(case, rep, config["seed"])
            providers = list(PROVIDERS)
            random.Random(f"{case['id']}:{rep}").shuffle(providers)
            for provider in providers:
                jobs.append((case, rep, provider, body))
    save(
        output / "requests.json",
        [{"case": c["id"], "rep": r, "provider": p, "body": b} for c, r, p, b in jobs],
    )
    if not live:
        return {"mode": "preview", "planned_calls": len(jobs)}
    if environment is None:
        raise ProbeError("MISSING-ENVIRONMENT")
    keys = {
        "jev": load_key(ROOT / ".armi/experiments/jev/api.key"),
        "deepseek": deepseek_key(environment),
    }
    semaphore = asyncio.Semaphore(3)
    stopped = asyncio.Event()
    rows = []
    async with httpx.AsyncClient(
        timeout=60, trust_env=False, follow_redirects=False
    ) as client:

        async def trial(case: dict, rep: int, provider: str, body: dict) -> None:
            async with semaphore:
                if stopped.is_set():
                    return
                row = {
                    "case": case["id"],
                    "rep": rep,
                    "provider": provider,
                    "started_utc": datetime.now(UTC).isoformat(),
                }
                if provider == "jev":
                    endpoint = "https://api.typesafe.ai/v1/systemone"
                    payload = body
                else:
                    endpoint = "https://api.deepseek.com/chat/completions"
                    payload = {
                        "model": "deepseek-flash",
                        "temperature": 0,
                        "thinking": {"type": "disabled"},
                        "max_tokens": 2048,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "system",
                                "content": "完成输入中的每一个choice问题。遵循state.armi_mood_rules。输出JSON对象，key严格对应questions，value是所选criteria选项字符串，不附解释或其他字段。",
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "state": body["state"],
                                        "questions": body["questions"],
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                    }
                row["request"] = payload
                start = time.perf_counter()
                try:
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {keys[provider]}"},
                        json=payload,
                    )
                    row["http_status"] = response.status_code
                    row["latency_ms"] = round((time.perf_counter() - start) * 1000)
                    if response.status_code != 200:
                        stopped.set()
                        raise ProbeError(f"HTTP-{response.status_code}")
                    raw = response.json()
                    row["response"] = raw
                    cost_bounds(provider, raw["usage"])
                    row["usage"] = raw["usage"]
                    choices, confidence = parse_choices(raw, provider)
                    row.update(choices=choices, confidence=confidence)
                    # Semantic correctness is scored even when joint choices violate a contract.
                    row["grade"] = grade(choices, case, None)
                    mood = derive(choices, case)
                    row.update(
                        status="succeeded", mood=mood, grade=grade(choices, case, mood)
                    )
                except httpx.RequestError:
                    row.update(
                        status="network_unknown", error="NETWORK-OUTCOME-UNKNOWN"
                    )
                except (
                    ProbeError,
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                ) as error:
                    row.update(
                        status="failed",
                        error=str(error)
                        if isinstance(error, ProbeError)
                        else "INVALID-RESPONSE",
                    )
                row.setdefault(
                    "latency_ms", round((time.perf_counter() - start) * 1000)
                )
                rows.append(row)
                save(output / f"{case['id']}-{rep}-{provider}.json", row)
                print(
                    json.dumps(
                        {
                            key: row[key]
                            for key in (
                                "case",
                                "rep",
                                "provider",
                                "status",
                                "latency_ms",
                            )
                        }
                    ),
                    flush=True,
                )

        await asyncio.gather(*(trial(*job) for job in jobs))
    result = {
        "planned_calls": len(jobs),
        "attempted_calls": len(rows),
        "failures": sum(row["status"] != "succeeded" for row in rows),
        "summary": summarize(rows, config),
    }
    save(output / "results.json", result)
    return result


def regrade(source: Path, output: Path) -> dict:
    """Reparse frozen responses without credentials, network or changing labels."""
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in config["cases"]}
    output.mkdir(parents=True, exist_ok=False)
    save(output / "config.json", config)
    save(
        output / "provenance.json",
        {
            "source": str(source),
            "network_calls": 0,
            "reason": "Accept two-decimal probability rounding; unchanged labels and responses",
        },
    )
    rows = []
    for provider in PROVIDERS:
        for path in source.glob(f"*-{provider}.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            row["original_status"] = row["status"]
            row["original_error"] = row.pop("error", None)
            if "response" in row:
                for field in ("choices", "confidence", "grade", "mood"):
                    row.pop(field, None)
                try:
                    choices, confidence = parse_choices(row["response"], provider)
                    row.update(choices=choices, confidence=confidence)
                    row["grade"] = grade(choices, cases[row["case"]], None)
                    mood = derive(choices, cases[row["case"]])
                    row.update(
                        status="succeeded",
                        mood=mood,
                        grade=grade(choices, cases[row["case"]], mood),
                    )
                except (
                    ProbeError,
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                ) as error:
                    row.update(
                        status="failed",
                        error=str(error)
                        if isinstance(error, ProbeError)
                        else "INVALID-RESPONSE",
                    )
            rows.append(row)
            save(output / path.name, row)
    result = {
        "planned_calls": len(config["cases"]) * config["repetitions"] * 2,
        "attempted_calls": len(rows),
        "failures": sum(row["status"] != "succeeded" for row in rows),
        "summary": summarize(rows, config),
    }
    save(output / "results.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/jev-mood-experiment.yaml"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--regrade-from", type=Path)
    args = parser.parse_args()
    try:
        if args.regrade_from is not None:
            if args.live:
                raise ProbeError("REGRADE-CANNOT-BE-LIVE")
            result = regrade(args.regrade_from, args.output)
        else:
            result = asyncio.run(
                run(
                    load_yaml_file(args.config),
                    args.output,
                    args.environment_root,
                    live=args.live,
                )
            )
    except Exception:
        print(
            "MOOD-EXPERIMENT-FAILED: inspect non-secret evidence; no automatic retry."
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return (
        int(
            result.get("failures", 0) > 0
            or result.get("attempted_calls", 0) != result.get("planned_calls", 0)
        )
        if args.live
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
