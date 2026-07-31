"""Strict parser for the persisted T-03 input artifact."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import (
    CandidateComponentDraft,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwner,
    CandidateRejection,
    CandidateViolation,
    SubjectChangeSet,
    SubjectCommitViolation,
)
from armi_kernel.contracts import ContractViolation, Digest

_TOP_KEYS = {
    "schema_version",
    "subject_id",
    "generation_id",
    "episode_id",
    "model_attempt_id",
    "base",
    "candidate_digest",
    "disposition",
    "experiences",
    "components",
    "rejections",
}


def parse_subject_change_set(value: bytes) -> SubjectChangeSet:
    try:
        raw = json.loads(value)
        if type(raw) is not dict:
            raise ValueError
        document = cast(dict[str, Any], raw)
        if (
            set(document) != _TOP_KEYS
            or document["schema_version"] != "armi.subject-change-set.v1"
        ):
            raise ValueError
        canonical = rfc8785.dumps(cast(Any, document))
        if canonical != value:
            raise ValueError
        base = _object(
            document["base"],
            {
                "subject_version",
                "state_epoch",
                "bundle_activation_id",
                "context_digest",
            },
        )
        experiences = tuple(
            _experience(item) for item in _array(document["experiences"], 16)
        )
        components = tuple(
            _component(item) for item in _array(document["components"], 12)
        )
        rejections = tuple(
            _rejection(item) for item in _array(document["rejections"], 16)
        )
        result = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            _uuid7(document["subject_id"]),
            _uuid7(document["generation_id"]),
            _uuid7(document["episode_id"]),
            _uuid7(document["model_attempt_id"]),
            _nonnegative(base["subject_version"]),
            _nonnegative(base["state_epoch"]),
            _uuid7(base["bundle_activation_id"]),
            Digest(_text(base["context_digest"])),
            Digest(_text(document["candidate_digest"])),
            CandidateDisposition(_text(document["disposition"])),
            experiences,
            components,
            rejections,
        )
        proposal_refs = [
            item.proposal_ref for item in (*experiences, *components, *rejections)
        ]
        if len(proposal_refs) != len(set(proposal_refs)):
            raise ValueError
        if result.disposition is not CandidateDisposition.CHANGE and (
            result.experiences or result.components
        ):
            raise ValueError
        return result
    except (
        CandidateViolation,
        ContractViolation,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise SubjectCommitViolation("SUBJECT-CHANGE-SET-INVALID") from None


def _experience(value: object) -> CandidateExperienceDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "first_person_gist",
            "uncertainty",
            "privacy_scope",
        },
    )
    uncertainty = item["uncertainty"]
    return CandidateExperienceDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _text(item["first_person_gist"]),
        None if uncertainty is None else _text(uncertainty),
        _text(item["privacy_scope"]),
    )


def _component(value: object) -> CandidateComponentDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "owner",
            "expected_version",
            "next_state",
            "next_state_digest",
        },
    )
    next_state = rfc8785.dumps(item["next_state"])
    return CandidateComponentDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        CandidateOwner(_text(item["owner"])),
        _positive(item["expected_version"]),
        next_state,
        Digest(_text(item["next_state_digest"])),
    )


def _rejection(value: object) -> CandidateRejection:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "owner",
            "code",
        },
    )
    return CandidateRejection(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        CandidateOwner(_text(item["owner"])),
        _text(item["code"]),
    )


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError
    result = cast(dict[str, Any], value)
    if set(result) != keys:
        raise ValueError
    return result


def _array(value: object, maximum: int) -> list[object]:
    if type(value) is not list:
        raise ValueError
    result = cast(list[object], value)
    if len(result) > maximum:
        raise ValueError
    return result


def _ordinals(value: object) -> tuple[int, ...]:
    values = _array(value, 8)
    if not values:
        raise ValueError
    return tuple(_positive(item) for item in values)


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value


def _uuid7(value: object) -> UUID:
    parsed = UUID(_text(value))
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError
    return parsed


def _nonnegative(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _positive(value: object) -> int:
    parsed = _nonnegative(value)
    if parsed == 0:
        raise ValueError
    return parsed


__all__ = ("parse_subject_change_set",)
