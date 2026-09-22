"""Isolated Jev prompt/primitive comparison; never calculate or commit Mood."""

from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese prompts intentionally preserve native punctuation.
import argparse
import asyncio
import math
import time
from pathlib import Path

import httpx
from armi_kernel import load_yaml_file
from armi_mood.api import JEV_MODEL, appraisal_questions
from experiment_jev import load_key, save

FIELDS = ("agency", "epistemic", "gain", "urgency")
ZH = {
    "agency": "根据 `event.content` 和 `context`，谁造成了正在评价的行为或后果？主体固定为 ARMI。引语中的我指引语的说话者，不自动指 ARMI；报告者不一定是行为者。",
    "epistemic": "根据 `context` 中的事实和 `event.content`，所述后果有什么证据？背景已有针对同一后果的核验时，消息里的转述不取消核验；仅有人声称时不能升级为已确认。",
    "gain": "根据 `context` 的 ARMI 已有目标和 `event.content`，本次事件促进该目标多少？只评价目标收益，不把刺激喜好、别人的收益、说话礼貌当成 ARMI 的目标达成；没有目标信息选 unknown，明确无目标收益选 level_0。",
    "urgency": "根据 `event.content` 和 `context`，ARMI 当前应对这件事有多紧迫？普通预约、别人正在忙、事情突然，不等于 ARMI 必须立即行动。缺少时间约束证据选 unknown，明确无需应对或无时间压力选 level_0。",
}
EN = {
    "agency": "Using `event.content` and `context`, who caused the focal action or outcome? The subject is always ARMI. First-person pronouns inside a quotation refer to its speaker, not automatically to ARMI. A reporter is not necessarily the actor.",
    "epistemic": "Using `context` and `event.content`, what evidence supports the described outcome? Verification of that same outcome in the background remains verification even if a message also reports it. A claim alone is not verification.",
    "gain": "Using ARMI's existing goals in `context` and `event.content`, how much progress does this event make toward those goals? Do not substitute pleasant presentation, someone else's benefit, or politeness for ARMI's goal progress. Missing goal information is unknown; explicitly no goal benefit is level_0.",
    "urgency": "Using `event.content` and `context`, how urgently must ARMI respond to this situation? An ordinary appointment, someone else being busy, or sudden onset does not by itself require urgent action by ARMI. Missing evidence is unknown; explicitly no need to act or no time pressure is level_0.",
}
EN_CRITERIA = {
    "agency": {
        "self": "ARMI caused it",
        "other": "A person other than ARMI caused it",
        "shared": "ARMI and another person jointly caused it",
        "circumstance": "Environment or nonhuman cause",
        "unknown": "The cause cannot be determined",
    },
    "epistemic": {
        "confirmed": "Direct observation, explicit factual record, or verification of the outcome",
        "reported": "Only an unverified claim or report about the outcome",
        "imagined": "Hypothetical or imagined outcome",
        "unknown": "Evidence type cannot be determined",
    },
    "gain": {
        "level_0": "Explicitly no goal progress",
        "level_1": "Small local progress",
        "level_2": "Part of the goal achieved",
        "level_3": "Major progress or main obstacle removed",
        "level_4": "Goal fully achieved or predicted outcome would fully achieve it",
        "unknown": "Insufficient information",
        "not_applicable": "Evidence establishes this dimension does not apply",
    },
    "urgency": {
        "level_0": "No response needed or no time pressure",
        "level_1": "Can wait a long time without losing an opportunity",
        "level_2": "Must respond within an ordinary time window",
        "level_3": "Must act soon to avoid losing an important opportunity",
        "level_4": "Immediate action required or consequences become unavoidable",
        "unknown": "Insufficient information",
        "not_applicable": "Evidence establishes this dimension does not apply",
    },
}


def request_body(case, *, context_language=None):
    original = appraisal_questions(())
    questions = {}
    for field in FIELDS:
        questions[f"baseline_{field}"] = original[field]
        criteria = original[field]["criteria"]
        if field == "agency":
            criteria = {
                **criteria,
                "self": "ARMI 自己造成",
                "other": "ARMI 以外的其他人造成",
                "shared": "ARMI 与别人共同造成",
            }
        questions[f"focused_zh_{field}"] = {
            "type": "choice",
            "instructions": ZH[field],
            "criteria": criteria,
        }
        questions[f"focused_en_{field}"] = {
            "type": "choice",
            "instructions": EN[field],
            "criteria": EN_CRITERIA[field],
        }
    questions["urgency_evidence"] = {
        "type": "choice",
        "instructions": "Do `context` and `event.content` provide enough information to assess ARMI's response time pressure, including an explicit absence of pressure?",
        "criteria": {
            "known": "Enough evidence, including explicit no pressure",
            "unknown": "Insufficient evidence",
            "not_applicable": "No applicable response task",
        },
    }
    questions["urgency_score"] = {
        "type": "score",
        "instructions": EN["urgency"].split("Missing evidence")[0],
        "criteria": [EN_CRITERIA["urgency"][f"level_{i}"] for i in range(5)],
    }
    questions["goal_gain_present"] = {
        "type": "noul",
        "instructions": "Do `context` and `event.content` explicitly support positive progress for an existing goal of ARMI? Pleasant presentation or another person's benefit alone is not goal progress for ARMI.",
        "criteria": {
            "true": "Positive progress for an existing ARMI goal is supported",
            "false": "No such progress is supported by the supplied information",
        },
    }
    if context_language is not None:
        # A/B changes only background language; both arms use identical English questions.
        if context_language not in {"zh", "en"}:
            raise ValueError("FACT-CONTEXT-LANGUAGE")
        questions = {
            name: question
            for name, question in questions.items()
            if name.startswith("focused_en_")
        }
    return {
        "model": JEV_MODEL,
        "state": {
            "event": {"id": case["id"], "content": case["scene"]},
            "context": case["context_en"]
            if context_language == "en"
            else case.get("context", []),
            "previous_situations": [],
        },
        "questions": questions,
    }


def validate_answer(answer, question):
    def bounded(value, upper=1):
        return (
            type(value) in (int, float) and math.isfinite(value) and 0 <= value <= upper
        )

    kind = question["type"]
    if not isinstance(answer, dict) or answer.get("type") != kind:
        return False
    if kind == "noul":
        return set(answer) == {"type", "noul"} and bounded(answer["noul"])
    keys = (
        {"type", "confidence", "probabilities", "choice"}
        if kind == "choice"
        else {"type", "confidence", "probabilities", "score", "legend"}
    )
    if set(answer) != keys or not bounded(answer["confidence"]):
        return False
    options = (
        question["criteria"]
        if kind == "choice"
        else {str(i): text for i, text in enumerate(question["criteria"])}
    )
    probabilities = answer["probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != set(options):
        return False
    if not all(bounded(p) for p in probabilities.values()) or not math.isclose(
        sum(probabilities.values()), 1, abs_tol=0.005 * len(options) + 1e-9
    ):
        return False
    if kind == "choice":
        choice = answer["choice"]
        return (
            isinstance(choice, str)
            and choice in options
            and math.isclose(
                probabilities[choice],
                max(probabilities.values()),
                rel_tol=0,
                abs_tol=1e-12,
            )
        )
    return (
        answer["legend"] == options
        and bounded(answer["score"], len(options) - 1)
        and math.isclose(
            answer["score"],
            sum(int(k) * p for k, p in probabilities.items()),
            abs_tol=0.005 * sum(range(len(options))) + 0.005,
        )
    )


async def run(config, output, *, live=False, transport=None, context_language=None):
    bodies = [
        request_body(case, context_language=context_language)
        for case in config["cases"]
    ]
    output.mkdir(parents=True, exist_ok=False)
    save(output / "config.json", config)
    key = load_key(None) if live else ""
    rows = []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, trust_env=False, transport=transport
    ) as client:
        for case, body in zip(config["cases"], bodies, strict=True):
            row = {"case": case["id"], "request": body, "status": "preview"}
            if live:
                start = time.perf_counter()
                try:
                    response = await client.post(
                        "https://api.typesafe.ai/v1/systemone",
                        json=body,
                        headers={"Authorization": "Bearer " + key},
                    )
                    response.raise_for_status()
                    raw = response.json()
                    row["response"] = raw
                    if (
                        not isinstance(raw, dict)
                        or raw.get("model") != JEV_MODEL
                        or not isinstance(raw.get("answers"), dict)
                        or set(raw["answers"]) != set(body["questions"])
                    ):
                        raise ValueError("FACT-CONTRACT")
                    usage = raw.get("usage", {})
                    if not isinstance(usage, dict) or any(
                        type(usage.get(k)) is not int or usage[k] < 0
                        for k in ("input_tokens", "output_tokens")
                    ):
                        raise ValueError("FACT-USAGE")
                    row.update({k: usage[k] for k in ("input_tokens", "output_tokens")})
                    row["invalid_answers"] = [
                        name
                        for name, question in body["questions"].items()
                        if not validate_answer(raw["answers"][name], question)
                    ]
                    row["mismatches"] = {}
                    variants = (
                        ("focused_en",)
                        if context_language is not None
                        else ("baseline", "focused_zh", "focused_en")
                    )
                    for variant in variants:
                        row["mismatches"][variant] = [
                            field
                            for field, accepted in case.get("expected", {}).items()
                            if f"{variant}_{field}" in row["invalid_answers"]
                            or raw["answers"][f"{variant}_{field}"]["choice"]
                            not in accepted
                        ]
                    row["status"] = (
                        "invalid_answers" if row["invalid_answers"] else "succeeded"
                    )
                except httpx.HTTPError, ValueError, TypeError, KeyError:
                    # Never retain exceptions or HTTP error bodies containing secrets.
                    row["status"] = "call_failed"
                row["latency_seconds"] = time.perf_counter() - start
            save(output / (case["id"] + ".json"), row)
            rows.append(row)
            if row["status"] == "call_failed":
                break
    save(output / "results.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--context-language", choices=("zh", "en"))
    args = parser.parse_args()
    rows = asyncio.run(
        run(
            load_yaml_file(args.config),
            args.output,
            live=args.live,
            context_language=args.context_language,
        )
    )
    print(
        {
            "cases": len(rows),
            "failures": sum(
                row["status"] in {"call_failed", "invalid_answers"} for row in rows
            ),
        }
    )
    return int(any(row["status"] in {"call_failed", "invalid_answers"} for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
