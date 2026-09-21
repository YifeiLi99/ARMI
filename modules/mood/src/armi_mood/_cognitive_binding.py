"""Owner binding of typed appraisal candidates to frozen references."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from armi_kernel.application import (
    CandidateBasis,
    CandidateFactClass,
    CandidateOwnerDraft,
)
from pydantic import ValidationError

if TYPE_CHECKING:
    from .api import (
        AppraisalEventSignalV3,
        MoodCognitionPort,
        MoodSemanticAppraisalCommand,
        SemanticAppraisalEvent,
    )
from ._cognitive_contract import MoodState


def preview_appraisal(event: SemanticAppraisalEvent) -> dict[str, object]:
    """Use the production policy without writing facts in isolated experiments."""
    from ._domain import derive_semantic_appraisal

    if event.previous_episode_id is not None:
        raise ValueError("MOOD-PREVIEW-PREVIOUS-REQUIRED")
    return asdict(derive_semantic_appraisal(event))


def semantic_appraisal_from_command(
    command: MoodSemanticAppraisalCommand,
) -> SemanticAppraisalEvent:
    from .api import (
        AppraisalAdjustment,
        AppraisalAgency,
        AppraisalCausality,
        AppraisalCertainty,
        AppraisalCompatibility,
        AppraisalConcern,
        AppraisalConcernTarget,
        AppraisalCoping,
        AppraisalDemand,
        AppraisalDemandLevel,
        AppraisalDirection,
        AppraisalEventPhase,
        AppraisalExpectedness,
        AppraisalIntentionality,
        AppraisalPowerBalance,
        AppraisalQuality,
        AppraisalResponseAccess,
        AppraisalSelfInvolvement,
        AppraisalSelfScope,
        AppraisalSignificance,
        AppraisalStandards,
        AppraisalTrajectory,
        AppraisalTransition,
        AppraisalUrgency,
        SemanticAppraisal,
        SemanticAppraisalEvent,
    )

    previous_id = (
        None
        if command.previous_episode_id is None
        else UUID(command.previous_episode_id)
    )
    value = command.appraisal
    return SemanticAppraisalEvent(
        AppraisalTransition(command.transition),
        previous_id,
        AppraisalEventPhase(command.event_phase),
        command.gist,
        SemanticAppraisal(
            tuple(
                AppraisalConcern(
                    AppraisalConcernTarget(item.target),
                    AppraisalSignificance(item.significance),
                    AppraisalDirection(item.direction),
                )
                for item in value.concerns
            ),
            AppraisalExpectedness(value.expectedness),
            AppraisalCertainty(value.outcome_certainty),
            AppraisalQuality(value.intrinsic_quality),
            AppraisalSelfInvolvement(value.self_involvement),
            None
            if value.demand is None
            else AppraisalDemand(
                AppraisalUrgency(value.demand.urgency),
                AppraisalDemandLevel(value.demand.effort),
            ),
            None
            if value.causality is None
            else AppraisalCausality(
                AppraisalAgency(value.causality.agency),
                AppraisalIntentionality(value.causality.intentionality),
            ),
            None
            if value.coping is None
            else AppraisalCoping(
                AppraisalResponseAccess(value.coping.response_access),
                AppraisalPowerBalance(value.coping.power_balance),
                AppraisalAdjustment(value.coping.adjustment),
            ),
            None
            if value.standards is None
            else AppraisalStandards(
                AppraisalCompatibility(value.standards.self_compatibility),
                AppraisalCompatibility(value.standards.norm_compatibility),
                AppraisalSelfScope(value.standards.self_scope),
            ),
            value.engagement,
        ),
        None
        if command.change_from_previous is None
        else AppraisalTrajectory(command.change_from_previous),
    )


def bind_appraisal_event(
    signal: AppraisalEventSignalV3,
    *,
    proposal_ref: str,
    bases: tuple[CandidateBasis, ...],
    current_components: tuple[tuple[str, int, bytes], ...],
) -> tuple[dict[str, Any] | None, str | None]:
    from .api import (
        MoodSemanticAppraisalCommand,
    )

    if len({item.target for item in signal.appraisal.concerns}) != len(
        signal.appraisal.concerns
    ):
        return None, "CANDIDATE-MOOD-TARGET-CONFLICT"
    current = next(
        (
            (version, canonical)
            for owner, version, canonical in current_components
            if owner == "mood"
        ),
        None,
    )
    mood_basis = next(
        (
            item
            for item in bases
            if item.item_kind == "mood"
            and current is not None
            and item.source_version == current[0]
        ),
        None,
    )
    if current is None or mood_basis is None:
        return None, "CANDIDATE-MOOD-CONTEXT"
    episode_basis = None
    if signal.episode_ref is not None:
        episode_ordinal = int(signal.episode_ref.partition(":")[2])
        episode_basis = next(
            (
                item
                for item in bases
                if item.ordinal == episode_ordinal
                and item.item_kind == "active_affective_episode"
                and item.source_ref is not None
            ),
            None,
        )
        if episode_basis is None or episode_basis.source_ref is None:
            return None, "CANDIDATE-MOOD-EPISODE"
        if episode_basis.source_ref.version != 7:
            return None, "CANDIDATE-MOOD-EPISODE"
    basis_refs = tuple(
        dict.fromkeys(
            (
                *signal.basis_refs,
                *((signal.episode_ref,) if signal.episode_ref is not None else ()),
                f"ctx:{mood_basis.ordinal}",
            )
        )
    )
    allowed_refs = {f"ctx:{item.ordinal}" for item in bases}
    if not set(basis_refs).issubset(allowed_refs):
        return None, "CANDIDATE-MOOD-BASIS"
    try:
        MoodState.model_validate_json(current[1], strict=True)
    except ValidationError:
        return None, "CANDIDATE-MOOD-STATE"
    event_command = MoodSemanticAppraisalCommand.model_construct(
        schema_kind="armi.mood-appraisal",
        transition=signal.transition,
        previous_episode_id=(
            None if episode_basis is None else str(episode_basis.source_ref)
        ),
        event_phase=signal.event_phase,
        gist=signal.gist,
        appraisal=signal.appraisal,
        change_from_previous=signal.change_from_previous,
    )
    return (
        {
            "proposal_ref": proposal_ref,
            "atomic_group_ref": "group:4",
            "basis_refs": basis_refs,
            "payload": {
                "proposal_kind": "component_changes",
                "fact_class": "subjective_understanding",
                "owner": "mood",
                "expected_version": current[0],
                "next_state": event_command,
            },
        },
        None,
    )


def bind_appraisal_draft(
    signal: AppraisalEventSignalV3,
    *,
    proposal_ref: str,
    bases: tuple[CandidateBasis, ...],
    current_components: tuple[tuple[str, int, bytes], ...],
    cognition: MoodCognitionPort,
) -> tuple[CandidateOwnerDraft | None, str | None]:
    from .api import (
        CandidateMoodDraft,
        MoodCandidateKind,
        MoodViolation,
    )

    proposal, error = bind_appraisal_event(
        signal,
        proposal_ref=proposal_ref,
        bases=bases,
        current_components=current_components,
    )
    if proposal is None or error is not None:
        return None, error or "CANDIDATE-MOOD-COMMAND"
    try:
        payload = cast(dict[str, object], proposal["payload"])
        command = cast("MoodSemanticAppraisalCommand", payload["next_state"])
        basis_refs = cast(tuple[str, ...], proposal["basis_refs"])
        ordinals = tuple(int(ref.partition(":")[2]) for ref in basis_refs)
        return (
            cognition.bind(
                CandidateMoodDraft(
                    proposal_ref,
                    cast(str, proposal["atomic_group_ref"]),
                    ordinals,
                    CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
                    cast(int, payload["expected_version"]),
                    MoodCandidateKind.APPRAISAL,
                    semantic_appraisal_from_command(command),
                )
            ),
            None,
        )
    except KeyError, TypeError, ValueError, ValidationError, MoodViolation:
        return None, "CANDIDATE-MOOD-COMMAND"
