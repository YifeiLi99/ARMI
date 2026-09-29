"""Real source Runtime, accelerated only between due work; real provider receipts."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid7

from armi_local_control import SimulationClock, private_directory

from tools.dialogue_lab_pricing import estimate_calls
from tools.dialogue_lab_support import LabError, save

if TYPE_CHECKING:
    from tools.dialogue_lab import DialogueLab


def collect_usage(lab: DialogueLab, *, start: str, end: str) -> dict[str, Any]:
    filters = {"start": start, "end": end}
    calls = []
    offset = 0
    while True:
        page = lab.admin("usage_list", {**filters, "limit": 100, "offset": offset})
        calls.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"]:
            break
        if not page["items"]:
            raise LabError("LAB-USAGE-PAGINATION-INCOMPLETE")
    details = [
        lab.admin("usage_read", {"call_id": call["receipt"]["call_id"]})
        for call in calls
    ]
    return {
        "calls": calls,
        "details": details,
        "summary": lab.admin("usage_summary", filters),
    }


def simulate(lab: DialogueLab, *, seconds: int) -> dict[str, object]:
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise LabError("LAB-SIMULATION-DURATION")
    if lab.admin("runtime_status")["status"] != "stopped":
        raise LabError("LAB-SIMULATION-REQUIRES-STOPPED-RUNTIME")
    clock = SimulationClock(lab.root, lab.config.environment_id)
    clock.initialize()
    directory = lab.root / "simulations" / str(uuid7())
    private_directory(directory)
    started = datetime.now(UTC).isoformat()
    report: dict[str, object] = {
        "status": "running",
        "requested_seconds": seconds,
        "started_at": started,
        "root": str(lab.root),
        "scenario": "continue_existing_subject_without_new_input",
        "time_mode": "real_execution_with_idle_time_injection",
    }
    save(directory / "report.json", report)
    with lab.admin_session():
        try:
            save(
                directory / "startup.json",
                lab.admin("environment_start", {"idempotency_key": str(uuid7())}),
            )
            save(directory / "initial-state.json", lab.status())
            window_started = time.monotonic()
            advanced = 0.0
            steps = 0
            last_progress = 0.0
            while time.monotonic() - window_started + advanced < seconds:
                remaining = seconds - (time.monotonic() - window_started + advanced)
                if remaining < 1:
                    time.sleep(remaining)
                    break
                result = lab.admin(
                    "advance_test_time",
                    {"seconds": int(remaining), "idempotency_key": str(uuid7())},
                )
                step = result["result"]
                advanced += step["advanced_seconds"]
                steps += 1
                elapsed = time.monotonic() - window_started + advanced
                if elapsed - last_progress >= 60:
                    report.update(
                        {
                            "simulated_seconds": elapsed,
                            "idle_seconds_skipped": advanced,
                            "steps": steps,
                        }
                    )
                    save(directory / "report.json", report)
                    last_progress = elapsed
                if step["status"] == "busy":
                    time.sleep(0.1)
            report.update(
                {
                    "idle_seconds_skipped": advanced,
                    "simulated_seconds": time.monotonic() - window_started + advanced,
                    "steps": steps,
                    "window_wall_seconds": time.monotonic() - window_started,
                }
            )
            save(directory / "final-state.json", lab.status())
            # Stop new work before taking the ledger snapshot; retain PostgreSQL for reads.
            save(
                directory / "runtime-stop.json",
                lab.admin("runtime_stop", {"idempotency_key": str(uuid7())}),
            )
            ended = datetime.now(UTC).isoformat()
            usage = collect_usage(lab, start=started, end=ended)
            save(directory / "usage.json", usage)
            cost_estimate = estimate_calls(usage["calls"])
            save(directory / "cost-estimate.json", cost_estimate)
            captures = []
            for episode in sorted(
                {
                    call["reference_id"]
                    for call in usage["calls"]
                    if call["reference_kind"] == "episode"
                }
            ):
                captures.append(str(lab.capture(episode_id=episode)))
            save(directory / "captures.json", captures)
            report.update(
                {
                    "status": "completed",
                    "ended_at": ended,
                    "usage": usage["summary"],
                    "call_count": len(usage["calls"]),
                    "cost_estimate": cost_estimate,
                    "directory": str(directory),
                    "coverage": "all_metered_calls_including_startup_and_shutdown",
                }
            )
        except BaseException as error:
            report.update(
                {
                    "status": "failed",
                    "error_code": str(error)
                    if isinstance(error, LabError)
                    else type(error).__name__,
                }
            )
            raise
        finally:
            try:
                save(
                    directory / "environment-stop.json",
                    lab.admin("environment_stop", {"idempotency_key": str(uuid7())}),
                )
            finally:
                save(directory / "report.json", report)
    return report
