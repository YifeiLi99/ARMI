"""Mind transitions shared by production commits and isolated experiments."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import CandidateFactClass

from ._concerns import CONCERN_RECORDS, apply_concern_changes
from ._motivation import MOTIVATION_RECORDS, apply_mind_appraisals

if TYPE_CHECKING:
    from .api import CandidateMindDraft, MindHead


def initial_mind_state() -> bytes:
    return rfc8785.dumps(
        {
            "schema_kind": "armi.mind",
            "understanding": [],
            "attention": [],
            "thoughts": [],
            "wishes": [],
            "motivations": [],
            "concerns": [],
            "motivation_states": [],
        }
    )


def validate_state(value: dict[str, object]) -> None:
    fields = {"understanding", "attention", "thoughts", "wishes", "motivations"}
    if (
        set(value) - {"concerns", "motivation_states"} != fields | {"schema_kind"}
        or value["schema_kind"] != "armi.mind"
    ):
        raise ValueError("invalid Mind state")
    for field in fields:
        raw_items = value[field]
        if type(raw_items) is not list:
            raise ValueError("invalid Mind text")
        items = cast(list[object], raw_items)
        if len(items) > 16 or any(
            type(item) is not str
            or not item.strip()
            or "\x00" in item
            or len(item) > 512
            for item in items
        ):
            raise ValueError("invalid Mind text")
    if "concerns" in value:
        CONCERN_RECORDS.validate_json(json.dumps(value["concerns"]), strict=True)
    if "motivation_states" in value:
        MOTIVATION_RECORDS.validate_json(
            json.dumps(value["motivation_states"]), strict=True
        )


def validate_candidate(value: CandidateMindDraft) -> None:
    from .api import MindViolation

    if (
        re.fullmatch(r"proposal:[1-9][0-9]{0,2}", value.proposal_ref) is None
        or re.fullmatch(r"group:[1-9][0-9]{0,2}", value.atomic_group_ref) is None
        or type(value.basis_ordinals) is not tuple
        or not 1 <= len(value.basis_ordinals) <= 8
        or any(
            type(item) is not int or not 1 <= item <= 999
            for item in value.basis_ordinals
        )
        or len(set(value.basis_ordinals)) != len(value.basis_ordinals)
        or type(value.fact_class) is not CandidateFactClass
        or type(value.expected_version) is not int
        or value.expected_version <= 0
        or type(value.canonical_next_state) is not bytes
        or len(value.concern_changes) > 4
        or len(value.mind_appraisals) > 4
    ):
        raise MindViolation("MIND-CANDIDATE")
    try:
        raw = json.loads(value.canonical_next_state)
        if (
            type(raw) is not dict
            or rfc8785.dumps(cast(Any, raw)) != value.canonical_next_state
        ):
            raise ValueError
        validate_state(cast(dict[str, object], raw))
    except UnicodeDecodeError, TypeError, ValueError:
        raise MindViolation("MIND-CANDIDATE") from None


def prepare_mind_change(
    current: MindHead,
    draft: CandidateMindDraft,
    *,
    now: datetime,
    commit_id: UUID,
    new_identity: Callable[[], UUID] = uuid7,
) -> bytes:
    from .api import MindViolation

    if draft.expected_version != current.version:
        raise MindViolation("MIND-HEAD-STALE", ("expected_version",))
    payload = json.loads(current.canonical_state)
    records = CONCERN_RECORDS.validate_json(
        json.dumps(payload["concerns"]), strict=True
    )
    next_payload = json.loads(draft.canonical_next_state)
    if "concerns" in next_payload and next_payload["concerns"] != payload["concerns"]:
        raise MindViolation("MIND-CONCERN-REPLACEMENT", ("next_state", "concerns"))
    try:
        records = apply_concern_changes(
            records,
            draft.concern_changes,
            now=now,
            commit_id=commit_id,
            basis_ordinals=draft.basis_ordinals,
            new_identity=new_identity,
        )
    except ValueError as error:
        raise MindViolation(str(error), ("concern_changes",)) from error
    next_payload["concerns"] = [item.model_dump(mode="json") for item in records]
    motivations = MOTIVATION_RECORDS.validate_json(
        json.dumps(payload["motivation_states"]), strict=True
    )
    if (
        "motivation_states" in next_payload
        and next_payload["motivation_states"] != payload["motivation_states"]
    ):
        raise MindViolation(
            "MIND-MOTIVATION-REPLACEMENT", ("next_state", "motivation_states")
        )
    motivations = apply_mind_appraisals(
        motivations,
        draft.mind_appraisals,
        now=now,
        commit_id=commit_id,
        basis_ordinals=draft.basis_ordinals,
        new_identity=new_identity,
    )
    next_payload["motivation_states"] = [
        item.model_dump(mode="json") for item in motivations
    ]
    return rfc8785.dumps(next_payload)


__all__ = (
    "initial_mind_state",
    "prepare_mind_change",
    "validate_candidate",
    "validate_state",
)
