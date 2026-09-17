"""Deterministic synthetic Mind scenarios; never connects to a running ARMI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import rfc8785
import yaml
from armi_kernel.application import CandidateBasis, CandidateFactClass
from armi_mind.api import (
    CONCERN_CHANGES,
    CandidateMindDraft,
    MindHead,
    MindState,
    MindViolation,
    bind_concern_changes,
    initial_mind_state,
    mind_context_items,
    mind_editable_state,
    mind_signals,
    prepare_mind_change,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Expect(Strict):
    accepted: bool = True
    code: str | None = None
    version: int | None = None
    concern_count: int | None = None
    signal_count: int | None = None


class Basis(Strict):
    alias: str = Field(min_length=1, max_length=80)
    kind: Literal[
        "creator_input", "tool_result", "current_activity", "subjective_understanding"
    ]
    summary: str = Field(min_length=1, max_length=1024)


class Change(Strict):
    action: Literal["change"]
    state: MindState | None = None
    concerns: list[dict[str, Any]] = Field(default_factory=list)
    expected_version: int | None = None
    save_as: str | None = None
    expect: Expect = Expect()


class Advance(Strict):
    action: Literal["advance"]
    seconds: int = Field(ge=0)
    expect: Expect = Expect()


class Event(Strict):
    action: Literal["event"]
    alias: str
    kind: Literal["creator_input", "activity_result"]
    activity: str | None = None
    expect: Expect = Expect()


class Snapshot(Strict):
    action: Literal["snapshot"]
    expect: Expect = Expect()


class Scenario(Strict):
    synthetic: Literal[True]
    initial: MindState | None = None
    context: list[Basis] = Field(default_factory=list)
    steps: list[
        Annotated[Change | Advance | Event | Snapshot, Field(discriminator="action")]
    ]


class ScenarioFailure(ValueError):
    pass


def run(scenario: Scenario) -> dict[str, Any]:
    sequence = 0

    def identity() -> UUID:
        nonlocal sequence
        sequence += 1
        return UUID(int=(1_800_000_000_000 << 80) | (7 << 76) | (2 << 62) | sequence)

    now = datetime(2026, 1, 1, tzinfo=UTC)
    head = MindHead(identity(), 1, initial_mind_state())
    if scenario.initial is not None:
        seed = CandidateMindDraft(
            "proposal:1",
            "group:1",
            (1,),
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            1,
            rfc8785.dumps(scenario.initial.model_dump(mode="json")),
        )
        head = MindHead(
            head.current_revision_id,
            1,
            prepare_mind_change(
                head, seed, now=now, commit_id=identity(), new_identity=identity
            ),
        )
    aliases: dict[str, UUID] = {}
    basis: dict[str, CandidateBasis] = {
        "mind": CandidateBasis(
            1,
            "mind",
            "mind",
            head.current_revision_id,
            1,
            "subjective_state",
            "private",
        )
    }
    for item in scenario.context:
        if item.alias in basis:
            raise ScenarioFailure("duplicate context alias")
        aliases[item.alias] = identity()
        basis[item.alias] = CandidateBasis(
            len(basis) + 1,
            "synthetic",
            item.kind,
            aliases[item.alias],
            1,
            "external_claim",
            "private",
        )
    event: dict[str, Any] = {}
    events: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for number, step in enumerate(scenario.steps, 1):
        before = head
        code: str | None = None
        path: list[str | int] = []
        try:
            if isinstance(step, Advance):
                now += timedelta(seconds=step.seconds)
            elif isinstance(step, Event):
                if step.activity is not None and step.activity not in aliases:
                    raise ScenarioFailure("unknown activity alias")
                if step.alias in basis and basis[step.alias].item_kind in {
                    "current_concern",
                    "current_activity",
                    "mind",
                }:
                    raise ScenarioFailure("event alias conflicts with an Owner object")
                if step.alias not in aliases:
                    aliases[step.alias] = identity()
                event_id = aliases[step.alias]
                event = dict(
                    event_purpose="consider_creator_input"
                    if step.kind == "creator_input"
                    else "consider_life_query_result",
                    event_ref=event_id,
                    event_at=events.get(step.alias, {}).get("event_at", now),
                    activity_id=aliases.get(step.activity or ""),
                )
                if step.alias in events and events[step.alias] != event:
                    raise ScenarioFailure("event alias cannot change its source")
                events[step.alias] = event
                basis[step.alias] = CandidateBasis(
                    basis[step.alias].ordinal
                    if step.alias in basis
                    else max(value.ordinal for value in basis.values()) + 1,
                    "synthetic",
                    "creator_input" if step.kind == "creator_input" else "tool_result",
                    event_id,
                    1,
                    "external_claim",
                    "private",
                )
            elif isinstance(step, Change):
                if step.save_as is not None and step.save_as in aliases:
                    raise ScenarioFailure("duplicate object alias")
                changes = CONCERN_CHANGES.validate_json(
                    json.dumps(step.concerns), strict=True
                )
                bound, ordinals, error, field_path = bind_concern_changes(
                    changes,
                    basis_by_ref=basis,
                    current_activity_id=next(
                        (
                            item.source_ref
                            for item in basis.values()
                            if item.item_kind == "current_activity"
                        ),
                        None,
                    ),
                )
                if error is not None or bound is None:
                    code, path = error, list(field_path)
                else:
                    state = (
                        step.state.model_dump(mode="json")
                        if step.state is not None
                        else json.loads(mind_editable_state(head.canonical_state))
                    )
                    draft = CandidateMindDraft(
                        "proposal:1",
                        "group:1",
                        tuple(sorted({1, *ordinals})),
                        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                        head.version
                        if step.expected_version is None
                        else step.expected_version,
                        rfc8785.dumps(state),
                        bound,
                    )
                    payload = prepare_mind_change(
                        head,
                        draft,
                        now=now,
                        commit_id=identity(),
                        new_identity=identity,
                    )
                    candidate_head = MindHead(identity(), head.version + 1, payload)
                    old_refs = {
                        item.source_ref
                        for item in mind_context_items(
                            head.canonical_state,
                            revision_id=head.current_revision_id,
                            version=head.version,
                            as_of=now,
                            purpose="consider_creator_input",
                        )
                        if item.item_kind == "current_concern"
                    }
                    current_items = mind_context_items(
                        payload,
                        revision_id=candidate_head.current_revision_id,
                        version=candidate_head.version,
                        as_of=now,
                        purpose="consider_creator_input",
                    )
                    created = [
                        item
                        for item in current_items
                        if item.item_kind == "current_concern"
                        and item.source_ref not in old_refs
                    ]
                    if step.save_as is not None and len(created) != 1:
                        raise ScenarioFailure(
                            "save_as requires exactly one newly created concern"
                        )
                    head = candidate_head
                    basis["mind"] = CandidateBasis(
                        1,
                        "mind",
                        "mind",
                        head.current_revision_id,
                        head.version,
                        "subjective_state",
                        "private",
                    )
                    if step.save_as is not None:
                        aliases[step.save_as] = created[0].source_ref
                    # Rebuild concern bindings from the Owner projection; closed references disappear.
                    basis = {
                        key: value
                        for key, value in basis.items()
                        if value.item_kind != "current_concern"
                    }
                    for item in current_items:
                        if item.item_kind == "current_concern":
                            alias = next(
                                (
                                    key
                                    for key, ref in aliases.items()
                                    if ref == item.source_ref
                                ),
                                str(item.source_ref),
                            )
                            ordinal = max(value.ordinal for value in basis.values()) + 1
                            basis[alias] = CandidateBasis(
                                ordinal,
                                "mind",
                                "current_concern",
                                item.source_ref,
                                item.source_version,
                                "subjective_state",
                                "private",
                            )
        except ValidationError as error:
            code = "MIND-SCHEMA"
            path = list(error.errors(include_input=False)[0]["loc"])
        except MindViolation as error:
            code = error.code
            path = list(error.field_path)
        signals = mind_signals(head.canonical_state, **event)
        content = mind_context_items(
            head.canonical_state,
            revision_id=head.current_revision_id,
            version=head.version,
            as_of=now,
            purpose="consider_creator_input",
            signals=signals,
        )
        before_json, after_json = (
            json.loads(before.canonical_state),
            json.loads(head.canonical_state),
        )
        row = dict(
            step=number,
            action=step.action,
            accepted=code is None,
            code=code,
            field_path=path,
            at=now.isoformat(),
            version=head.version,
            diff={
                key: {"before": before_json.get(key), "after": value}
                for key, value in after_json.items()
                if before_json.get(key) != value
            },
            snapshot=after_json,
            signals=[
                {**asdict(signal), "due": signal.eligible_at <= now}
                for signal in signals
            ],
        )
        checks = dict(
            accepted=code is None,
            code=code,
            version=head.version,
            concern_count=sum(item.item_kind == "current_concern" for item in content),
            signal_count=len(signals),
        )
        mismatches = [
            key
            for key, expected in step.expect.model_dump().items()
            if (expected is not None or key == "accepted") and checks[key] != expected
        ]
        row["assertion_failures"] = mismatches
        results.append(row)
        if mismatches:
            break
    return dict(
        synthetic=True,
        scope="Mind mechanisms only; events do not invoke a model",
        passed=not any(row["assertion_failures"] for row in results),
        steps=results,
    )


class ScenarioLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ScenarioFailure("YAML keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args()
    try:
        document = yaml.load(
            args.scenario.read_text(encoding="utf-8"), Loader=ScenarioLoader
        )
        result = run(Scenario.model_validate_json(json.dumps(document), strict=True))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as error:
        result = {
            "synthetic": True,
            "passed": False,
            "error": type(error).__name__,
            "detail": str(error),
        }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(
            "Mind 离线机制测试: 通过" if result["passed"] else "Mind 离线机制测试: 失败"
        )
        for row in result.get("steps", []):
            print(
                f"{row['step']}. {row['action']} {'接受' if row['accepted'] else '拒绝'} v{row['version']} {row['code'] or ''}"
            )
            print(
                json.dumps(
                    {
                        key: row[key]
                        for key in ("diff", "signals", "assertion_failures")
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
        if "detail" in result:
            print(result["detail"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
