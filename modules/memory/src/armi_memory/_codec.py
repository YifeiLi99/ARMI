"""Canonical owner payloads and historical memory codecs."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryAccessibility,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemorySourceKind,
    MemoryViolation,
)


def encode(value: CandidateMemoryDraft | CandidateMemoryRevisionDraft) -> bytes:
    common: dict[str, object] = {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "source_kind": value.source_kind.value,
        "summary": value.summary,
        "mechanism_identity": value.mechanism_identity,
        "privacy_scope": value.privacy_scope,
    }
    if isinstance(value, CandidateMemoryDraft):
        common["operation"] = "form"
        common["source_experience_ref"] = value.source_experience_ref
    else:
        common.update(
            operation="revise",
            memory_id=str(value.memory_id),
            current_revision_id=str(value.current_revision_id),
            expected_head_version=value.expected_head_version,
            revision_kind=value.revision_kind.value,
            accessibility=value.accessibility.value,
            uncertainty=value.uncertainty,
            related_memory_id=(
                None
                if value.related_memory_id is None
                else str(value.related_memory_id)
            ),
            relation_kind=(
                None if value.relation_kind is None else value.relation_kind.value
            ),
            mechanism_config_identity=value.mechanism_config_identity,
        )
    return rfc8785.dumps(cast(Any, common))


def decode(payload: bytes) -> CandidateMemoryDraft | CandidateMemoryRevisionDraft:
    try:
        value = json.loads(payload)
        if type(value) is not dict or rfc8785.dumps(cast(Any, value)) != payload:
            raise ValueError
        item = cast(dict[str, object], value)
        proposal_ref = str(item["proposal_ref"])
        atomic_group_ref = str(item["atomic_group_ref"])
        basis_ordinals = tuple(cast(list[int], item["basis_ordinals"]))
        fact_class = CandidateFactClass(str(item["fact_class"]))
        source_kind = MemorySourceKind(str(item["source_kind"]))
        summary = str(item["summary"])
        mechanism_identity = str(item["mechanism_identity"])
        privacy_scope = str(item["privacy_scope"])
        if item["operation"] == "form":
            return CandidateMemoryDraft(
                proposal_ref,
                atomic_group_ref,
                basis_ordinals,
                fact_class,
                str(item["source_experience_ref"]),
                source_kind,
                summary,
                mechanism_identity,
                privacy_scope,
            )
        related = item["related_memory_id"]
        relation = item["relation_kind"]
        return CandidateMemoryRevisionDraft(
            proposal_ref,
            atomic_group_ref,
            basis_ordinals,
            fact_class,
            memory_id=UUID(str(item["memory_id"])),
            current_revision_id=UUID(str(item["current_revision_id"])),
            expected_head_version=cast(int, item["expected_head_version"]),
            revision_kind=MemoryRevisionKind(str(item["revision_kind"])),
            accessibility=MemoryAccessibility(str(item["accessibility"])),
            uncertainty=(
                None if item["uncertainty"] is None else str(item["uncertainty"])
            ),
            related_memory_id=None if related is None else UUID(str(related)),
            relation_kind=None
            if relation is None
            else MemoryRelationKind(str(relation)),
            source_kind=source_kind,
            summary=summary,
            mechanism_identity=mechanism_identity,
            mechanism_config_identity=str(item["mechanism_config_identity"]),
            privacy_scope=privacy_scope,
        )
    except KeyError, TypeError, ValueError, MemoryViolation:
        raise MemoryViolation("MEMORY-CODEC") from None


def decode_wire(
    value: object, *, revision: bool
) -> CandidateMemoryDraft | CandidateMemoryRevisionDraft:
    if revision and type(value) is CandidateMemoryRevisionDraft:
        return value
    if not revision and type(value) is CandidateMemoryDraft:
        return value
    try:
        item = cast(dict[str, object], value)
        proposal_ref = str(item["proposal_ref"])
        atomic_group_ref = str(item["atomic_group_ref"])
        basis_ordinals = tuple(cast(list[int], item["basis_ordinals"]))
        fact_class = CandidateFactClass(str(item["fact_class"]))
        source_kind = MemorySourceKind(str(item["source_kind"]))
        summary = str(item["summary"])
        mechanism_identity = str(item["mechanism_identity"])
        privacy_scope = str(item["privacy_scope"])
        if not revision:
            return CandidateMemoryDraft(
                proposal_ref,
                atomic_group_ref,
                basis_ordinals,
                fact_class,
                str(item["source_experience_ref"]),
                source_kind,
                summary,
                mechanism_identity,
                privacy_scope,
            )
        related = item.get("related_memory_id")
        relation = item.get("relation_kind")
        return CandidateMemoryRevisionDraft(
            proposal_ref,
            atomic_group_ref,
            basis_ordinals,
            fact_class,
            memory_id=UUID(str(item["memory_id"])),
            current_revision_id=UUID(str(item["current_revision_id"])),
            expected_head_version=cast(int, item["expected_head_version"]),
            revision_kind=MemoryRevisionKind(str(item["revision_kind"])),
            accessibility=MemoryAccessibility(str(item["accessibility"])),
            uncertainty=(
                None if item.get("uncertainty") is None else str(item["uncertainty"])
            ),
            related_memory_id=None if related is None else UUID(str(related)),
            relation_kind=None
            if relation is None
            else MemoryRelationKind(str(relation)),
            source_kind=source_kind,
            summary=summary,
            mechanism_identity=mechanism_identity,
            mechanism_config_identity=str(item["mechanism_config_identity"]),
            privacy_scope=privacy_scope,
        )
    except KeyError, TypeError, ValueError, MemoryViolation:
        raise MemoryViolation("MEMORY-CODEC-LEGACY") from None


__all__ = ("decode", "decode_wire", "encode")
