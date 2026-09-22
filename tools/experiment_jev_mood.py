"""Replay isolated synthetic event sequences through the production Mood contract."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from armi_kernel import load_yaml_file
from armi_mood.api import (
    JEV_MODEL,
    DynamicsParameters,
    apply_appraisal,
    appraisal_questions,
    current_affect,
    initial_dynamics,
    parse_appraisal_response,
)
from experiment_jev import load_key, save

ROOT = Path(__file__).resolve().parents[1]


def request_body(case, state, event_id):
    previous = [
        {
            "id": item.situation_id,
            "content": item.summary,
            "appraisal": item.appraisal.model_dump(mode="json"),
        }
        for item in state.episodes
    ]
    return {
        "model": JEV_MODEL,
        "state": {
            "event": {"id": event_id, "content": case["scene"]},
            "context": case.get("context", []),
            "previous_situations": previous,
        },
        "questions": appraisal_questions(tuple(item["id"] for item in previous)),
    }


def grade(case, evaluated, response):
    choices = {name: answer["choice"] for name, answer in evaluated.answers.items()}
    errors = {
        name: {"actual": choices[name], "accepted": accepted}
        for name, accepted in case.get("expected", {}).items()
        if choices[name] not in accepted
    }
    emotions = {item.kind.value for item in response.emotions}
    return {
        "appraisal_errors": errors,
        "missing_emotions": sorted(set(case.get("required_emotions", [])) - emotions),
        "forbidden_emotions": sorted(
            set(case.get("forbidden_emotions", [])) & emotions
        ),
    }


async def run(config, output, *, live=False, key_file=None, transport=None):
    output.mkdir(parents=True, exist_ok=True)
    save(output / "config.json", config)
    rows = []
    key = load_key(key_file) if live else ""
    start = datetime(2026, 9, 22, tzinfo=UTC)
    states = {}
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, trust_env=False, transport=transport
    ) as client:
        for index, case in enumerate(config["cases"]):
            sequence = case["sequence"]
            state = states.setdefault(
                sequence, initial_dynamics(start, DynamicsParameters())
            )
            at = start + timedelta(seconds=60 * index)
            event_id = str(uuid5(NAMESPACE_URL, "armi:mood-experiment:" + case["id"]))
            body = request_body(case, state, event_id)
            row = {
                "case": case["id"],
                "sequence": sequence,
                "request": body,
                "status": "preview",
            }
            if live:
                before = time.perf_counter()
                try:
                    result = await client.post(
                        "https://api.typesafe.ai/v1/systemone",
                        json=body,
                        headers={"Authorization": "Bearer " + key},
                    )
                    result.raise_for_status()
                    raw = result.json()
                    row["response"] = raw
                    usage = raw.get("usage", {})
                    if all(
                        type(usage.get(name)) is int and usage[name] >= 0
                        for name in ("input_tokens", "output_tokens")
                    ):
                        row.update(
                            input_tokens=usage["input_tokens"],
                            output_tokens=usage["output_tokens"],
                        )
                    evaluated = parse_appraisal_response(
                        raw,
                        event_id=event_id,
                        situations=tuple(item.situation_id for item in state.episodes),
                    )
                    updated = apply_appraisal(
                        state,
                        event_id=event_id,
                        situation_id=evaluated.situation_id,
                        appraisal=evaluated.appraisal,
                        at=at,
                        summary=case["scene"],
                    )
                    states[sequence] = updated
                    episode = next(
                        item
                        for item in updated.episodes
                        if item.situation_id == evaluated.situation_id
                    )
                    row.update(
                        status="succeeded",
                        appraisal=evaluated.appraisal.model_dump(mode="json"),
                        affect=current_affect(updated, at).model_dump(mode="json"),
                        emotions=[
                            item.model_dump(mode="json")
                            for item in episode.response.emotions
                        ],
                        grade=grade(case, evaluated, episode.response),
                        input_tokens=evaluated.input_tokens,
                        output_tokens=evaluated.output_tokens,
                    )
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                    # Do not retain exception text: transports may contain credentials.
                    row.update(
                        status="failed",
                        error="MOOD-EXPERIMENT-CALL-FAILED",
                        error_type=type(error).__name__,
                    )
                    if isinstance(error, httpx.HTTPStatusError):
                        row["http_status"] = error.response.status_code
                row["latency_seconds"] = time.perf_counter() - before
            rows.append(row)
            save(output / (case["id"] + ".json"), row)
            if row["status"] == "failed":
                break  # No fabricated continuation after an unassessed event.
    summary = {
        "planned_calls": len(config["cases"]) if live else 0,
        "attempted_calls": len(rows) if live else 0,
        "failures": sum(row["status"] == "failed" for row in rows),
        "appraisal_errors": sum(
            len(row.get("grade", {}).get("appraisal_errors", {})) for row in rows
        ),
        "emotion_errors": sum(
            len(row.get("grade", {}).get("missing_emotions", []))
            + len(row.get("grade", {}).get("forbidden_emotions", []))
            for row in rows
        ),
        "input_tokens": sum(row.get("input_tokens", 0) for row in rows),
        "output_tokens": sum(row.get("output_tokens", 0) for row in rows),
        "estimated_usd": sum(row.get("input_tokens", 0) for row in rows)
        * 0.042
        / 1000000,
        "pricing": {
            "verified_on": "2026-09-22",
            "input_usd_per_million": 0.042,
            "output_usd_per_million": 0,
            "source": "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
            "kind": "public-list-price-estimate-not-account-bill",
        },
        "latencies_seconds": [
            row["latency_seconds"] for row in rows if "latency_seconds" in row
        ],
        "limitation": "Synthetic contract checks, not accuracy of human psychological simulation.",
    }
    save(output / "results.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs/jev-mood-experiment.yaml"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        run(
            load_yaml_file(args.config),
            args.output,
            live=args.live,
            key_file=args.key_file,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(result["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
