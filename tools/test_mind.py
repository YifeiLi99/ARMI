"""Replay frozen primitive appraisals with the production Mind algorithm, offline."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random
from typing import Literal

import yaml
from armi_attention.api import SocialCycle
from armi_mind.api import (
    Association,
    DimensionEvent,
    DynamicsParameters,
    GroundedObject,
    MindChoice,
    MindEvidence,
    MindObjectState,
    MindVariable,
    Opportunity,
    SocialEvidence,
    contact_drive,
    dimensions_projection,
    initial_dimensions,
    project_mind_object,
    update_dimensions,
    update_mind_object,
)
from pydantic import BaseModel, ConfigDict, Field


class ContinuousStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str
    seconds: float = Field(ge=0)
    running: bool = True
    focused: bool = False
    event: SocialEvidence | None = None
    result: Literal["delivered", "unknown", "failed", "defer", "release"] | None = None


class ContinuousScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    synthetic: Literal[True]
    seed: int
    person_ref: str
    steps: tuple[ContinuousStep, ...]


def run_continuous(scenario: ContinuousScenario) -> dict[str, object]:
    parameters = DynamicsParameters()
    states = initial_dimensions(parameters)
    random = Random(scenario.seed)
    cycle = SocialCycle.begin(random.random)
    active_seconds = 0.0
    trace: list[dict[str, object]] = []
    for index, step in enumerate(scenario.steps):
        active_seconds += step.seconds if step.running else 0
        if step.event is not None:
            states = update_dimensions(
                states,
                evidence=DimensionEvent(social=step.event),
                event_key=str(index),
                basis_refs=(step.label,),
                active_seconds=active_seconds,
                parameters=parameters,
            )
            if (
                step.event.received_contact
                and step.event.person_ref == scenario.person_ref
            ):
                cycle = SocialCycle.begin(random.random, input_ref=str(index))
        if step.result == "defer" or step.result == "release":
            cycle = cycle.decided(
                outcome=step.result,
                reason=step.label,
                episode_ref=str(index),
                active_seconds=active_seconds,
            )
        elif step.result is not None:
            cycle = cycle.decided(
                outcome="express",
                reason=step.label,
                episode_ref=str(index),
                active_seconds=active_seconds,
            )
            cycle = (
                cycle.delivered(active_seconds=active_seconds)
                if step.result == "delivered"
                else cycle.interrupted(
                    active_seconds=active_seconds, reason=step.result
                )
            )
        if (
            cycle.phase in {"waiting", "deferred", "released"}
            and active_seconds >= cycle.review_at
        ):
            cycle = SocialCycle.begin(
                random.random, input_ref=cycle.input_ref, unanswered=cycle.unanswered
            )
        drive = contact_drive(
            states, person_ref=scenario.person_ref, active_seconds=active_seconds
        )
        triggered = step.running and cycle.ready(
            drive=drive, active_seconds=active_seconds, focused=step.focused
        )
        if triggered:
            cycle = cycle.model_copy(update={"phase": "cognition"})
        trace.append(
            {
                "step": step.label,
                "active_seconds": active_seconds,
                "dimensions": dimensions_projection(
                    states, active_seconds=active_seconds
                ),
                "drive": drive * (0.75 if step.focused else 1),
                "triggered": triggered,
                "cycle": cycle.model_dump(),
            }
        )
    return {
        "synthetic": True,
        "passed": True,
        "calibrated": False,
        "main_model_calls": 0,
        "steps": trace,
    }


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: str = Field(min_length=1)
    object: str = Field(min_length=1)
    seconds: int = Field(ge=0)
    ratings: dict[MindVariable, MindChoice]
    association: Association = Association.ACTIVE
    opportunity: Opportunity = Opportunity.AVAILABLE
    expected_eligible: bool
    expected_exploration: float | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    synthetic: Literal[True]
    steps: tuple[Step, ...]


class ScenarioLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("YAML keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def run(scenario: Scenario) -> dict[str, object]:
    objects: dict[str, MindObjectState] = {}
    results: list[dict[str, object]] = []
    start = datetime(2026, 9, 22, tzinfo=UTC)
    for step in scenario.steps:
        at = start + timedelta(seconds=step.seconds)
        state = update_mind_object(
            MindEvidence(
                GroundedObject("synthetic", step.object),
                step.event,
                ("frozen:scenario",),
                at,
                tuple(step.ratings.items()),
                step.association,
                step.opportunity,
            ),
            previous=objects.get(step.object),
        )
        objects[step.object] = state
        projection = project_mind_object(state, at=at, consumed_versions=frozenset())
        from armi_mind.api import derive_mind, mind_condition_eligible

        failures = []
        if (
            mind_condition_eligible(state, consumed_versions=frozenset())
            != step.expected_eligible
        ):
            failures.append("eligible")
        if (
            step.expected_exploration is not None
            and derive_mind(state.variables).exploration != step.expected_exploration
        ):
            failures.append("exploration")
        results.append({"event": step.event, "state": projection, "failures": failures})
    return {
        "synthetic": True,
        "passed": not any(row["failures"] for row in results),
        "calibrated": False,
        "main_model_calls": 0,
        "steps": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    try:
        scenario = (
            ContinuousScenario if args.continuous else Scenario
        ).model_validate_json(
            json.dumps(
                yaml.load(
                    args.scenario.read_text(encoding="utf-8"), Loader=ScenarioLoader
                )
            )
        )
        result = (
            run_continuous(scenario)
            if isinstance(scenario, ContinuousScenario)
            else run(scenario)
        )
    except (ValueError, TypeError, OSError, yaml.YAMLError) as error:
        result = {"passed": False, "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
