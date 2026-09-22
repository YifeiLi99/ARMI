from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
import rfc8785
from armi_context._application import (
    ContextPipeline,
    _context_request,
)
from armi_context._compiler import DeterministicContextCompiler
from armi_context._dialogue import PostgreSQLContextDialogueRead
from armi_context._postgresql import (
    ContextEpisodeSnapshot,
    ContextMaterialSource,
    PostgreSQLContextRepository,
)
from armi_context.api import ContextDialogueItem, ContextItemDisposition
from armi_interaction.api import InteractionContextTurn
from armi_kernel.application import ConsiderationSignal
from armi_kernel.contracts import Digest, TraceId


def _snapshot(
    memory_payloads: tuple[tuple[object, ...], ...],
    *,
    has_memory_records: bool = True,
    relationship_payloads: tuple[tuple[object, ...], ...] = (),
    relationship_commitment_payloads: tuple[tuple[object, ...], ...] = (),
    relationship_issue_payloads: tuple[tuple[object, ...], ...] = (),
    capability_state_payloads: tuple[tuple[object, ...], ...] = (),
    scene_id: object | None = None,
    scene_bytes: bytes | None = None,
    creator_prompt: object | None = None,
    subject_prompt: object | None = None,
    purpose: str = "consider_creator_input",
    opportunity_source_kind: str = "external_evidence",
    activity_summary_bytes: bytes = b'{"activities":[]}',
    component_payloads: tuple[tuple[object, ...], ...] = (),
    experience_context: tuple[object, ...] = (),
) -> ContextEpisodeSnapshot:
    source_ref = uuid7()
    return cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            subject_id=uuid7(),
            subject_version=3,
            state_epoch=1,
            bundle_activation_id=uuid7(),
            opportunity_id=uuid7(),
            purpose=purpose,
            component_payloads=component_payloads,
            scene_id=scene_id,
            scene_bytes=scene_bytes,
            memory_payloads=memory_payloads,
            experience_context=experience_context,
            has_memory_records=has_memory_records,
            relationship_payloads=relationship_payloads,
            relationship_commitment_payloads=relationship_commitment_payloads,
            relationship_issue_payloads=relationship_issue_payloads,
            activity_summary_bytes=activity_summary_bytes,
            capability_state_payloads=capability_state_payloads,
            opportunity_source_ref=source_ref,
            opportunity_source_version=1,
            autonomy_context=None,
            opportunity_source_kind=opportunity_source_kind,
            opportunity_available_after=datetime(2026, 1, 1, tzinfo=UTC),
            opportunity_expires_at=None,
            evidence=None,
            fixed_prompt=SimpleNamespace(source_id=uuid7(), source_version=1),
            creator_prompt=creator_prompt,
            subject_prompt=subject_prompt,
            policy_version="context-policy.v1",
            mechanism_identity="armi.context-compiler.layered",
            trace_id=TraceId("1" * 32),
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            consideration_signals=(),
        ),
    )


def _memory(accessibility: str) -> tuple[object, ...]:
    payload = rfc8785.dumps(
        {
            "source_kind": "reported",
            "fact_class": "external_claim",
            "summary": f"{accessibility} memory",
            "uncertainty": None,
            "accessibility": accessibility,
        }
    )
    return uuid7(), 2, payload, accessibility


def test_concerns_are_private_separate_and_exclude_finished_history() -> None:
    concern = {
        "concern_id": str(uuid7()),
        "question": "A private unresolved question",
        "reason": "A new clue",
        "resolution_condition": "A reliable answer",
        "understanding": "No answer yet",
        "review": {"kind": "review", "after_seconds": 300, "reason": "Check later"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_commit_id": str(uuid7()),
        "basis_ordinals": [1],
        "state": "waiting",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "review_at": "2026-01-01T00:05:00+00:00",
    }
    mind = {
        "schema_kind": "armi.mind",
        "motivation_states": [],
        "thoughts": [],
        "concerns": [
            concern,
            {**concern, "state": "resolved", "question": "Finished history"},
        ],
    }
    snapshot = _snapshot(
        (), component_payloads=(("mind", uuid7(), 2, rfc8785.dumps(mind)),)
    )
    snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "observed_at": datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
                "autonomy_context": b'{"current_time":"2026-01-01T00:10:00+00:00","last_considered_at":null}',
            }
        ),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
    )
    concerns = [item for item in request.items if item.item_kind == "current_concern"]
    assert len(concerns) == 1
    assert concerns[0].content is not None
    detail = json.loads(concerns[0].content)
    assert detail["elapsed_seconds"] == 600
    assert detail["consideration_reason"] == "ongoing_concern"
    mind_content = next(
        item.content for item in request.items if item.item_kind == "mind"
    )
    assert mind_content is not None
    assert "concerns" not in json.loads(mind_content)
    other = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(**{**vars(snapshot), "purpose": "consider_other_human_input"}),
    )
    other_request = _context_request(
        other,
        None,
        b"fixed prompt",
    )
    assert not any(item.item_kind == "current_concern" for item in other_request.items)
    assert not any(
        "private unresolved" in (item.content or "") for item in other_request.items
    )


def test_active_creator_prompt_is_frozen_by_revision_in_future_context() -> None:
    revision_id = uuid7()
    snapshot = _snapshot(
        (),
        creator_prompt=SimpleNamespace(
            source_id=revision_id,
            source_version=3,
        ),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
        (),
        b"distinguish facts from guesses",
    )

    item = next(value for value in request.items if value.item_kind == "creator_prompt")
    assert item.source.reference == revision_id
    assert item.source.version == 3
    assert item.content == "distinguish facts from guesses"
    old_compiled = DeterministicContextCompiler().compile(request)

    next_revision_id = uuid7()
    next_snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "creator_prompt": SimpleNamespace(
                    source_id=next_revision_id,
                    source_version=4,
                ),
            }
        ),
    )
    next_request = _context_request(
        next_snapshot,
        None,
        b"fixed prompt",
        (),
        b"distinguish observations, claims, and unknowns",
    )
    next_item = next(
        value for value in next_request.items if value.item_kind == "creator_prompt"
    )

    assert item.source.reference == revision_id
    assert item.content == "distinguish facts from guesses"
    assert next_item.source.reference == next_revision_id
    assert next_item.source.version == 4
    assert (
        old_compiled.manifest_bytes
        != DeterministicContextCompiler().compile(next_request).manifest_bytes
    )


def test_exact_life_query_result_is_current_runtime_evidence() -> None:
    source_id = uuid7()
    snapshot = _snapshot(())
    snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "purpose": "consider_life_query_result",
                "opportunity_source_kind": "life_query_result",
                "opportunity_source_ref": source_id,
                "evidence": SimpleNamespace(
                    source_id=source_id,
                    source_version=1,
                    source_kind="life_query_result",
                ),
            }
        ),
    )
    request = _context_request(
        snapshot,
        b'{"status":"succeeded","retrieval_kind":"exact_query"}',
        b"fixed prompt",
    )

    evidence = next(
        item for item in request.items if item.item_kind == "current_evidence"
    )
    assert evidence.source.reference == source_id
    assert evidence.source.kind == "life_query_result"
    assert evidence.trust_class.value == "runtime_authority"


def test_codex_task_context_exposes_registered_manifest_digest() -> None:
    source_id = uuid7()
    manifest_digest = Digest.from_bytes(b"registered task manifest")
    snapshot = _snapshot((), purpose="consider_codex_task")
    snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "evidence": SimpleNamespace(
                    source_id=source_id,
                    source_version=1,
                    source_kind="codex_task_source",
                    task_manifest_digest=manifest_digest,
                ),
            }
        ),
    )
    request = _context_request(
        snapshot,
        rfc8785.dumps(
            {
                "schema_kind": "armi.codex-task-source",
                "objective": "收集资料",
            }
        ),
        b"fixed prompt",
    )

    evidence = next(
        item for item in request.items if item.item_kind == "codex_task_source"
    )
    document = json.loads(cast(str, evidence.content))
    assert document["task_manifest_digest"] == manifest_digest.value
    assert document["objective"] == "收集资料"


def test_autonomy_opportunity_is_required_runtime_evidence() -> None:
    scene_id = uuid7()
    trigger = b'{"kind":"creator_outreach_absence"}'
    snapshot = _snapshot(
        (),
        scene_id=scene_id,
        scene_bytes=b'{"status":"open"}',
        purpose="consider_autonomous_life",
        opportunity_source_kind="autonomy_plan",
    )
    snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(**{**vars(snapshot), "autonomy_context": trigger}),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
    )

    evidence = next(
        item for item in request.items if item.item_kind == "current_life_opportunity"
    )
    assert evidence.required
    assert evidence.trust_class.value == "runtime_authority"


def test_light_check_uses_bounded_owner_projections_without_private_recall() -> None:
    from dataclasses import replace

    from armi_context.api import autonomy_check_items

    component_id = uuid7()
    components = (
        (
            "self",
            component_id,
            7,
            rfc8785.dumps({"name": "ARMI", "self_description": "independent " * 300}),
        ),
        (
            "mind",
            uuid7(),
            2,
            rfc8785.dumps(
                {
                    "schema_kind": "armi.mind",
                    "thoughts": [],
                    "concerns": [],
                    "motivation_states": [],
                }
            ),
        ),
        (
            "mood",
            uuid7(),
            3,
            rfc8785.dumps(
                {
                    "schema_kind": "armi.mood-snapshot",
                    "active_episodes": [],
                    "active_emotions": [],
                    "quality": {"status": "not_evaluated", "unknown": []},
                    "current": {"valence": 0, "arousal": 0},
                }
            ),
        ),
        ("life_mode", uuid7(), 1, b'{"mode":"awake"}'),
    )
    snapshot = _snapshot(
        (_memory("accessible"),),
        purpose="consider_autonomy_check",
        component_payloads=components,
        capability_state_payloads=(
            (
                uuid7(),
                1,
                rfc8785.dumps(
                    {
                        "capability_kind": "codex.delegated-work",
                        "availability_status": "available",
                        "authorization_status": "authorized",
                        "tool_instructions": "FORBIDDEN_TOOL_BODY",
                    }
                ),
                "authorized",
            ),
        ),
        opportunity_source_kind="autonomy_plan",
    )
    snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "autonomy_context": b'{"current_time":"2026-01-01T00:00:00Z","last_engage":false}',
            }
        ),
    )
    request = _context_request(
        snapshot,
        None,
        b"personality " * 500,
    )
    contents = {
        item.item_kind: json.loads(item.content)
        for item in request.items
        if item.content is not None
    }
    assert "current_memory" not in contents
    assert "tool_instructions" not in json.dumps(contents)
    assert (
        contents["capability_catalog"]["codex.delegated-work"]["authorization"]
        == "authorized"
    )
    source = next(item for item in request.items if item.item_kind == "self")
    assert source.source.reference == component_id and source.source.version == 7
    assert contents["self"]["self_description"]["omitted_characters"] > 0
    assert contents["mind"] == {"open_concerns": 0, "open_motivations": 0}
    concern_template = replace(
        source,
        item_kind="current_concern",
        content='{"question":"unfinished","state":"waiting"}',
    )
    raw = [
        replace(
            source,
            item_kind="mind",
            content='{"open_concerns_count":12,"open_motivations_count":5}',
        ),
        replace(
            source, item_kind="current_life_opportunity", content='{"autonomy":{}}'
        ),
    ]
    projected = autonomy_check_items(
        raw + [concern_template] * 12, signalled_refs=frozenset()
    )
    assert sum(item.item_kind == "current_concern" for item in projected) == 4
    opportunity = next(
        item for item in projected if item.item_kind == "current_life_opportunity"
    )
    assert opportunity.content is not None
    assert json.loads(opportunity.content)["omitted_concerns_and_motivations"] == 13


def test_active_subject_prompt_is_frozen_and_changes_only_future_context() -> None:
    revision_id = uuid7()
    snapshot = _snapshot(
        (),
        subject_prompt=SimpleNamespace(source_id=revision_id, source_version=1),
    )
    first = _context_request(
        snapshot,
        None,
        b"fixed prompt",
        (),
        None,
        b'{"schema_kind":"armi.subject-prompt"}',
    )
    item = next(value for value in first.items if value.item_kind == "subject_prompt")
    assert item.source.reference == revision_id
    assert item.source.version == 1
    assert item.source.kind == "subject_prompt"

    next_revision_id = uuid7()
    next_snapshot = cast(
        ContextEpisodeSnapshot,
        SimpleNamespace(
            **{
                **vars(snapshot),
                "subject_prompt": SimpleNamespace(
                    source_id=next_revision_id,
                    source_version=2,
                ),
            }
        ),
    )
    second = _context_request(
        next_snapshot,
        None,
        b"fixed prompt",
        (),
        None,
        b'{"schema_kind":"armi.subject-prompt","revision":2}',
    )
    next_item = next(
        value for value in second.items if value.item_kind == "subject_prompt"
    )
    assert item.source.reference == revision_id
    assert next_item.source.reference == next_revision_id
    assert DeterministicContextCompiler().compile(first).manifest_bytes != (
        DeterministicContextCompiler().compile(second).manifest_bytes
    )


def test_capability_state_separates_availability_authorization_and_desire() -> None:
    unavailable_id = uuid7()
    unavailable = (
        unavailable_id,
        2,
        rfc8785.dumps(
            {
                "schema_kind": "armi.capability-state",
                "capability_ref": str(unavailable_id),
                "capability_kind": "codex.delegated-work",
                "operation": "execute",
                "availability_status": "unavailable",
                "authorization_status": "unauthorized",
                "current_request": None,
                "effective_grant": None,
            }
        ),
        "unauthorized",
    )
    request_id = uuid7()
    denied_id = uuid7()
    denied = (
        denied_id,
        2,
        rfc8785.dumps(
            {
                "schema_kind": "armi.capability-state",
                "capability_ref": str(denied_id),
                "capability_kind": "codex.delegated-work",
                "operation": "execute",
                "availability_status": "available",
                "authorization_status": "denied",
                "current_request": {
                    "request_ref": str(request_id),
                    "request_version": 2,
                    "status": "denied",
                    "requested_scope": {
                        "scope_kind": "codex_delegated_work",
                        "workspace_scope": "isolated_ephemeral",
                        "artifact_scope": "explicit_only",
                        "network_access": False,
                        "purpose": "delegate_codex_work",
                        "valid_for_seconds": 3600,
                        "max_uses": 1,
                    },
                    "resolution_reason_class": "creator_denied",
                    "created_at": "2026-01-02T00:00:00+00:00",
                },
                "effective_grant": None,
            }
        ),
        "denied",
    )
    request = _context_request(
        _snapshot((), capability_state_payloads=(unavailable, denied)),
        None,
        b"fixed prompt",
    )
    states = tuple(
        item for item in request.items if item.item_kind.startswith("capability_state_")
    )
    assert {item.item_kind for item in states} == {
        "capability_state_unauthorized",
        "capability_state_denied",
    }
    documents = [json.loads(item.content or "{}") for item in states]
    unavailable_document = next(
        item for item in documents if item["capability_ref"] == str(unavailable_id)
    )
    denied_document = next(
        item for item in documents if item["authorization_status"] == "denied"
    )
    assert unavailable_document["availability_status"] == "unavailable"
    assert unavailable_document["authorization_status"] == "unauthorized"
    assert denied_document["availability_status"] == "available"
    assert denied_document["current_request"]["request_ref"] == str(request_id)
    assert denied_document["current_request"]["resolution_reason_class"] == (
        "creator_denied"
    )
    assert "desire" not in denied_document
    denied_item = next(
        item for item in states if item.item_kind == "capability_state_denied"
    )
    assert denied_item.source.version is not None
    assert denied_item.source.version <= (1 << 53) - 1
    DeterministicContextCompiler().compile(request)


def test_context_includes_only_naturally_accessible_memory_heads() -> None:
    request = _context_request(
        _snapshot((_memory("available"), _memory("faded"), _memory("forgotten"))),
        None,
        b"fixed prompt",
    )
    memory_items = tuple(
        item for item in request.items if item.item_kind == "current_memory"
    )
    assert tuple(item.source.version for item in memory_items) == (2, 2)
    assert tuple(item.relevance for item in memory_items) == (85, 70)
    assert all("forgotten memory" not in (item.content or "") for item in memory_items)

    compiled = DeterministicContextCompiler().compile(request)
    assert all(
        item.disposition is ContextItemDisposition.INCLUDED
        for item in compiled.items
        if item.candidate.item_kind == "current_memory"
    )


def test_maintenance_context_separates_memory_work_from_subject_self_check() -> None:
    memories = (_memory("available"), _memory("forgotten"))
    experience_id = uuid7()
    accepted_at = datetime(2026, 1, 2, tzinfo=UTC)
    memory_request = _context_request(
        _snapshot(
            memories,
            purpose="maintain_subjective_memory",
            opportunity_source_kind="maintenance_phase_revision",
            experience_context=(
                SimpleNamespace(
                    experience_id=experience_id,
                    fact_class="external_claim",
                    first_person_gist="Creator 明确让我记住生日。",
                    occurred_at=accepted_at,
                    accepted_at=accepted_at,
                    source_perspective="creator_claim",
                    uncertainty=None,
                    maintenance_source=True,
                ),
            ),
        ),
        None,
        b"fixed prompt",
    )
    assert (
        len(
            [
                item
                for item in memory_request.items
                if item.item_kind == "current_memory"
            ]
        )
        == 1
    )
    memory_phase = next(
        item
        for item in memory_request.items
        if item.item_kind == "current_maintenance_phase"
    )
    assert memory_phase.required
    frozen_experience = next(
        item
        for item in memory_request.items
        if item.item_kind == "maintenance_experience"
    )
    assert frozen_experience.required
    assert frozen_experience.source.reference == experience_id
    assert "Creator 明确让我记住生日" in (frozen_experience.content or "")
    assert "forgotten memory" not in "".join(
        item.content or "" for item in memory_request.items
    )

    self_check_request = _context_request(
        _snapshot(
            memories,
            purpose="perform_subject_self_check",
            opportunity_source_kind="maintenance_phase_revision",
        ),
        None,
        b"fixed prompt",
    )
    assert not any(
        item.item_kind == "current_memory" for item in self_check_request.items
    )
    assert next(
        item
        for item in self_check_request.items
        if item.item_kind == "current_maintenance_phase"
    ).required
    assert next(
        item
        for item in self_check_request.items
        if item.item_kind == "current_activities"
    ).required


def test_context_distinguishes_no_natural_recall_from_no_database_record() -> None:
    request = _context_request(
        _snapshot((_memory("forgotten"),)),
        None,
        b"fixed prompt",
    )
    memory_items = tuple(item for item in request.items if item.item_kind == "memory")
    assert len(memory_items) == 1
    assert memory_items[0].content is None
    assert memory_items[0].unavailable_reason == "CTX-MEMORY-NOT-RECALLABLE"

    none = _context_request(
        _snapshot((), has_memory_records=False),
        None,
        b"fixed prompt",
    )
    empty = next(item for item in none.items if item.item_kind == "memory")
    assert empty.unavailable_reason == "CTX-MEMORY-NONE"


@pytest.mark.asyncio
async def test_optional_recent_turn_without_owner_source_is_omitted() -> None:
    repository = object.__new__(PostgreSQLContextDialogueRead)
    repository._evidence = AsyncMock()
    repository._evidence.find_by_interaction.return_value = None
    turn = InteractionContextTurn(
        uuid7(),
        1,
        "creator_input",
        uuid7(),
        datetime.now(UTC),
        "Creator",
        "creator",
        "text",
    )

    source = await repository._resolve(
        cast(Any, SimpleNamespace(transaction=object())),
        turn,
        human_speaker="creator",
    )

    assert source is None


def test_context_includes_current_relationship_or_explicitly_reports_none() -> None:
    relationship_id = uuid7()
    payload = rfc8785.dumps(
        {
            "scope": "creator_social",
            "facts": [
                {"kind": "shared_experience", "summary": "我们进行过一次真实交流。"}
            ],
            "interpretation": "我正在从实际交往中了解创造者。",
            "boundaries": [],
            "status": "active",
        }
    )
    snapshot = _snapshot(
        (),
        relationship_payloads=((relationship_id, 2, payload),),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
    )
    item = next(
        item for item in request.items if item.item_kind == "current_relationship"
    )
    assert item.source.reference == relationship_id
    assert item.source.version == 2
    assert item.trust_class.value == "subjective_state"

    empty_request = _context_request(
        _snapshot(()),
        None,
        b"fixed prompt",
    )
    empty = next(
        item for item in empty_request.items if item.item_kind == "current_relationship"
    )
    assert empty.content == '{"status":"none"}'
    assert empty.required


def test_context_includes_current_life_material_with_revision_identity() -> None:
    material_id = uuid7()
    source = cast(
        ContextMaterialSource,
        SimpleNamespace(
            material_id=material_id,
            head_version=4,
        ),
    )
    payload = rfc8785.dumps(
        {
            "material_kind": "diary",
            "title": "今天",
            "body": "这是当前完整正文。",
            "metadata": {"mood": "calm"},
            "material_status": "active",
            "privacy_status": "private",
        }
    )
    request = _context_request(
        _snapshot(()),
        None,
        b"fixed prompt",
        ((source, payload),),
    )
    item = next(item for item in request.items if item.item_kind == "current_material")
    assert item.section.value == "material"
    assert item.source.reference == material_id
    assert item.source.version == 4
    assert item.trust_class.value == "subjective_state"
    assert "当前完整正文" in cast(str, item.content)
    assert '"privacy_status":"private"' in cast(str, item.content)


def test_other_human_context_excludes_unscoped_private_life_content() -> None:
    relationship_id = uuid7()
    relationship_payload = rfc8785.dumps(
        {
            "scope": "other_human_social",
            "facts": [
                {
                    "kind": "shared_experience",
                    "summary": "我和当前对方有一段独立交流。",
                }
            ],
            "interpretation": "这是当前精确对方的关系。",
            "boundaries": [],
            "status": "active",
        }
    )
    material_source = cast(
        ContextMaterialSource,
        SimpleNamespace(
            material_id=uuid7(),
            head_version=1,
        ),
    )
    request = _context_request(
        _snapshot(
            (_memory("available"),),
            relationship_payloads=(
                (
                    relationship_id,
                    1,
                    relationship_payload,
                ),
            ),
            capability_state_payloads=(
                (
                    uuid7(),
                    1,
                    b'{"secret":"creator-capability"}',
                    "authorized",
                ),
            ),
            purpose="consider_other_human_input",
            activity_summary_bytes=b'{"activities":[{"goal":"private-activity"}]}',
            component_payloads=(
                (
                    "mind",
                    uuid7(),
                    1,
                    b'{"thoughts":["other-relationship-secret"],"concerns":[],"motivation_states":[]}',
                ),
            ),
        ),
        None,
        b"fixed prompt",
        (
            (
                material_source,
                b'{"title":"private-material-title","body":"private-material-body"}',
            ),
        ),
    )
    compiled = DeterministicContextCompiler().compile(request).compiled.canonical_bytes
    assert b"other_human_social" in compiled
    assert b"available memory" not in compiled
    assert b"private-material" not in compiled
    assert b"private-activity" not in compiled
    assert b"creator-capability" not in compiled
    assert b"other-relationship-secret" in compiled


def test_commitment_context_crosses_scenes_without_copying_recent_scene_text() -> None:
    commitment_id = uuid7()
    commitment_payload = rfc8785.dumps(
        {
            "party_role": "subject",
            "scope": "主动联系",
            "content": "联系前先询问是否方便。",
            "status": "active",
            "last_event_kind": "established",
            "last_event_summary": "我明确作出了联系前先询问的承诺。",
        }
    )
    commitment = (
        commitment_id,
        3,
        commitment_payload,
        "active",
    )
    first_scene = rfc8785.dumps({"scene_key": "private-alpha"})
    second_scene = rfc8785.dumps({"scene_key": "private-beta"})
    requests = tuple(
        _context_request(
            _snapshot(
                (),
                relationship_commitment_payloads=(commitment,),
                scene_id=uuid7(),
                scene_bytes=scene,
            ),
            None,
            b"fixed prompt",
        )
        for scene in (first_scene, second_scene)
    )
    commitment_contents = tuple(
        next(
            item.content
            for item in request.items
            if item.item_kind == "current_relationship_commitment"
        )
        for request in requests
    )
    scene_contents = tuple(
        next(
            item.content for item in request.items if item.item_kind == "current_scene"
        )
        for request in requests
    )
    assert commitment_contents[0] == commitment_contents[1]
    assert "private-alpha" not in cast(str, commitment_contents[0])
    assert "private-beta" not in cast(str, commitment_contents[0])
    assert scene_contents[0] != scene_contents[1]


def test_recent_scene_turns_are_scoped_to_the_supplied_scene_snapshot() -> None:
    def request(scene_key: str, text: str, speaker_label: str | None = None):
        visible_text = text if speaker_label is None else f"[{speaker_label}] {text}"
        payload = rfc8785.dumps({"speaker": "creator", "text": visible_text})
        source = ContextDialogueItem(
            uuid7(),
            1,
            "creator",
            text,
            datetime(2026, 8, 6, 10, tzinfo=UTC),
            "text",
            speaker_label,
        )
        reply_payload = rfc8785.dumps({"speaker": "armi", "text": "reply"})
        reply_source = ContextDialogueItem(
            uuid7(),
            1,
            "armi",
            "reply",
            datetime(2026, 8, 6, 10, 1, tzinfo=UTC),
            "text",
        )
        return _context_request(
            _snapshot(
                (),
                scene_id=uuid7(),
                scene_bytes=rfc8785.dumps({"scene_key": scene_key}),
            ),
            None,
            b"fixed prompt",
            recent_scene_payloads=(
                (source, payload),
                (reply_source, reply_payload),
            ),
        )

    alpha = request("alpha", "alpha only")
    beta = request("beta", "beta only")
    alpha_turns = tuple(
        item.content for item in alpha.items if item.item_kind == "recent_scene_turn"
    )
    beta_turns = tuple(
        item.content for item in beta.items if item.item_kind == "recent_scene_turn"
    )
    assert len(alpha_turns) == len(beta_turns) == 2
    assert "alpha only" in cast(str, alpha_turns[0])
    assert "beta only" not in cast(str, alpha_turns[0])
    assert "beta only" in cast(str, beta_turns[0])
    assert "alpha only" not in cast(str, beta_turns[0])
    labelled = request("group", "group turn", "小明")
    labelled_turns = tuple(
        item.content for item in labelled.items if item.item_kind == "recent_scene_turn"
    )
    assert "[小明] group turn" in cast(str, labelled_turns[0])


def test_recent_scene_keeps_unpaired_input_and_proactive_response() -> None:
    occurred_at = datetime(2026, 8, 6, 10, tzinfo=UTC)
    proactive = ContextDialogueItem(
        uuid7(), 1, "armi", "我先来找你。", occurred_at, "text"
    )
    unanswered = ContextDialogueItem(
        uuid7(), 1, "creator", "你刚才为什么没回答。", occurred_at, "text"
    )
    request = _context_request(
        _snapshot(
            (),
            scene_id=uuid7(),
            scene_bytes=rfc8785.dumps({"scene_key": "default"}),
        ),
        None,
        b"fixed prompt",
        recent_scene_payloads=(
            (proactive, rfc8785.dumps({"speaker": "armi", "text": proactive.text})),
            (
                unanswered,
                rfc8785.dumps({"speaker": "creator", "text": unanswered.text}),
            ),
        ),
    )

    dialogue = [
        item.content for item in request.items if item.item_kind == "recent_scene_turn"
    ]
    assert len(dialogue) == 2
    assert "我先来找你" in cast(str, dialogue[0])
    assert "为什么没回答" in cast(str, dialogue[1])


def test_recent_scene_preserves_text_and_voice_channel_switches() -> None:
    occurred_at = datetime(2026, 8, 6, 10, tzinfo=UTC)
    sources = (
        ContextDialogueItem(uuid7(), 1, "creator", "文字开场", occurred_at, "text"),
        ContextDialogueItem(uuid7(), 1, "armi", "语音回答", occurred_at, "live_voice"),
        ContextDialogueItem(
            uuid7(), 1, "creator", "语音追问", occurred_at, "live_voice"
        ),
        ContextDialogueItem(uuid7(), 1, "armi", "文字收尾", occurred_at, "text"),
    )
    request = _context_request(
        _snapshot(
            (),
            scene_id=uuid7(),
            scene_bytes=rfc8785.dumps({"scene_key": "default"}),
        ),
        None,
        b"fixed prompt",
        recent_scene_payloads=tuple(
            (source, rfc8785.dumps({"speaker": source.speaker, "text": source.text}))
            for source in sources
        ),
    )

    dialogue = [
        cast(str, item.content)
        for item in request.items
        if item.item_kind == "recent_scene_turn"
    ]
    assert len(dialogue) == 4
    assert all(
        source.text is not None and source.text in dialogue[index]
        for index, source in enumerate(sources)
    )


def test_recent_scene_artifact_contract_supports_text_voice_and_parties() -> None:
    logical_kind = PostgreSQLContextDialogueRead._logical_kind
    assert (
        logical_kind(speaker="creator", modality="text", human_speaker="creator")
        == "creator.input.text"
    )
    assert (
        logical_kind(speaker="creator", modality="live_voice", human_speaker="creator")
        == "creator.input.live_voice.transcript"
    )
    assert (
        logical_kind(speaker="armi", modality="text", human_speaker="creator")
        == "creator.response.text"
    )
    assert (
        logical_kind(
            speaker="other_human", modality="text", human_speaker="other_human"
        )
        == "other_human.input.text"
    )
    assert (
        logical_kind(speaker="armi", modality="text", human_speaker="other_human")
        == "other-human.response.text"
    )
    assert callable(ContextPipeline._publish)


def test_context_hides_forgotten_commitment_but_keeps_open_issue() -> None:
    forgotten_payload = rfc8785.dumps(
        {
            "party_role": "subject",
            "scope": "提醒",
            "content": "提醒一次。",
            "status": "forgotten",
            "last_event_kind": "forgotten",
            "last_event_summary": "这项承诺已不再能被自然想起。",
        }
    )
    issue_payload = rfc8785.dumps(
        {
            "kind": "commitment_violation",
            "summary": "这项承诺曾被违背。问题仍未解决。",
            "status": "open",
        }
    )
    request = _context_request(
        _snapshot(
            (),
            relationship_commitment_payloads=(
                (
                    uuid7(),
                    4,
                    forgotten_payload,
                    "forgotten",
                ),
            ),
            relationship_issue_payloads=((uuid7(), 4, issue_payload),),
        ),
        None,
        b"fixed prompt",
    )
    unavailable = next(
        item for item in request.items if item.item_kind == "relationship_commitment"
    )
    assert unavailable.unavailable_reason == "CTX-COMMITMENT-NOT-RECALLABLE"
    assert not any(
        item.item_kind == "current_relationship_commitment" for item in request.items
    )
    issue = next(
        item for item in request.items if item.item_kind == "current_relationship_issue"
    )
    assert "问题仍未解决" in cast(str, issue.content)


def test_context_consumes_owner_projection_without_interpreting_psychology(
    monkeypatch,
) -> None:
    from armi_kernel.application import PsychologicalContextItem

    source_id = uuid7()
    snapshot = _snapshot(
        (), component_payloads=(("mind", source_id, 7, b"owner-private-format"),)
    )
    projection = PsychologicalContextItem(
        "mind",
        "mind",
        source_id,
        7,
        "Owner-defined subjective summary",
        True,
        90,
    )
    monkeypatch.setattr(
        "armi_context._application.mind_context_items",
        lambda *args, **kwargs: (projection,),
    )
    request = _context_request(
        snapshot,
        None,
        b"fixed prompt",
    )
    item = next(item for item in request.items if item.item_kind == "mind")
    assert item.content == projection.content
    assert item.source.reference == source_id
    assert item.source.version == 7


@pytest.mark.asyncio
async def test_context_freeze_consumes_only_included_signal_objects():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    included, omitted = (
        ConsiderationSignal("mind", uuid7(), version, "review_time_reached", now)
        for version in ("included-version", "omitted-version")
    )
    repository = object.__new__(PostgreSQLContextRepository)
    transitions = SimpleNamespace(freeze_signals=AsyncMock())
    episode = SimpleNamespace(trace_id=TraceId("1" * 32), subject_id=uuid7())
    repository._opportunity_transitions = cast(Any, transitions)
    repository._episodes = cast(
        Any, SimpleNamespace(mark_context_prepared=AsyncMock(return_value=episode))
    )
    unit = SimpleNamespace(
        transaction=SimpleNamespace(execute=AsyncMock()),
        work=SimpleNamespace(enqueue=AsyncMock(), complete=AsyncMock()),
        audit=SimpleNamespace(append=AsyncMock()),
        environment_id=uuid7(),
    )
    items = tuple(
        SimpleNamespace(
            candidate=SimpleNamespace(
                source=SimpleNamespace(
                    kind="mind_concern", reference=signal.object_ref, version=1
                ),
                section=SimpleNamespace(value="subject_state"),
                layer=SimpleNamespace(value="subject_state"),
                item_kind="current_concern",
                trust_class=SimpleNamespace(value="subjective"),
            ),
            ordinal=index,
            disposition=SimpleNamespace(value=disposition),
            reason_code="CTX-TEST",
            content_bytes=1,
        )
        for index, (signal, disposition) in enumerate(
            ((included, "included"), (omitted, "omitted")), start=1
        )
    )
    artifact = SimpleNamespace(
        artifact_id=SimpleNamespace(value=uuid7()),
        content_digest=Digest("sha256:" + "1" * 64),
    )
    snapshot = SimpleNamespace(
        opportunity_id=uuid7(),
        observed_at=now,
        consideration_signals=(included, omitted),
    )
    await repository.settle_prepared(
        cast(Any, unit),
        lease=cast(Any, object()),
        episode_id=uuid7(),
        result=cast(Any, SimpleNamespace(items=items)),
        manifest_artifact=cast(Any, artifact),
        compiled_artifact=cast(Any, artifact),
        snapshot=cast(Any, snapshot),
    )
    transitions.freeze_signals.assert_awaited_once_with(
        unit.transaction,
        opportunity_id=snapshot.opportunity_id,
        signals=(included,),
        frozen_at=now,
    )
