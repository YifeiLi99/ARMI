"""Replay frozen primitive appraisals with the production Mind algorithm, offline."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from armi_mind.api import (
    Association,
    GroundedObject,
    MindChoice,
    MindEvidence,
    MindObjectState,
    MindVariable,
    Opportunity,
    project_mind_object,
    update_mind_object,
)
from pydantic import BaseModel, ConfigDict, Field


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
    args = parser.parse_args()
    try:
        scenario = Scenario.model_validate_json(
            json.dumps(
                yaml.load(
                    args.scenario.read_text(encoding="utf-8"), Loader=ScenarioLoader
                )
            )
        )
        result = run(scenario)
    except (ValueError, TypeError, OSError, yaml.YAMLError) as error:
        result = {"passed": False, "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
