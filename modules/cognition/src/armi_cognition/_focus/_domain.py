"""Cognition-owned focus transitions within the common Subject Commit."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import CandidateFactClass

from ._concerns import CONCERN_RECORDS, apply_concern_changes

if TYPE_CHECKING:
    from .api import CandidateFocusDraft, FocusHead


def initial_focus_state() -> bytes:
    return rfc8785.dumps({"schema_kind": "armi.focus", "concerns": []})


def validate_state(value: dict[str, object]) -> None:
    if (
        set(value) != {"schema_kind", "concerns"}
        or value["schema_kind"] != "armi.focus"
    ):
        raise ValueError("invalid focus state")
    CONCERN_RECORDS.validate_json(json.dumps(value["concerns"]), strict=True)


def validate_candidate(value: CandidateFocusDraft) -> None:
    from .api import FocusViolation

    if (
        re.fullmatch(r"proposal:[1-9][0-9]{0,2}", value.proposal_ref) is None
        or re.fullmatch(r"group:[1-9][0-9]{0,2}", value.atomic_group_ref) is None
        or not 1 <= len(value.basis_ordinals) <= 8
        or any(type(i) is not int or not 1 <= i <= 999 for i in value.basis_ordinals)
        or len(set(value.basis_ordinals)) != len(value.basis_ordinals)
        or type(value.fact_class) is not CandidateFactClass
        or type(value.expected_version) is not int
        or value.expected_version <= 0
        or len(value.concern_changes) > 4
    ):
        raise FocusViolation("FOCUS-CANDIDATE")
    raw = json.loads(value.canonical_next_state)
    if rfc8785.dumps(raw) != value.canonical_next_state:
        raise FocusViolation("FOCUS-CANDIDATE")
    validate_state(raw)


def prepare_focus_change(
    current: FocusHead,
    draft: CandidateFocusDraft,
    *,
    now: datetime,
    commit_id: UUID,
    new_identity: Callable[[], UUID] = uuid7,
) -> bytes:
    from .api import FocusViolation

    if draft.expected_version != current.version:
        raise FocusViolation("FOCUS-HEAD-STALE")
    if draft.canonical_next_state != current.canonical_state:
        raise FocusViolation("FOCUS-REPLACEMENT-FORBIDDEN")
    records = CONCERN_RECORDS.validate_json(
        json.dumps(json.loads(current.canonical_state)["concerns"]), strict=True
    )
    try:
        updated = apply_concern_changes(
            records,
            draft.concern_changes,
            now=now,
            commit_id=commit_id,
            basis_ordinals=draft.basis_ordinals,
            new_identity=new_identity,
        )
    except ValueError as error:
        raise FocusViolation(str(error)) from error
    return rfc8785.dumps(
        {
            "schema_kind": "armi.focus",
            "concerns": [r.model_dump(mode="json") for r in updated],
        }
    )
