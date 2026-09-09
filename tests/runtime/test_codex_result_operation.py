from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition.api import CognitionOperationSnapshot
from armi_effect.api import EffectStatus
from armi_evidence.api import EvidenceId
from armi_expression.api import ExpressionOperationSnapshot
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInteractionId,
    CreatorOperationPhase,
    OpportunityId,
)
from armi_kernel.contracts import Digest
from armi_runtime.application.creator_projection import operation_wire
from armi_runtime.application.operation_assembler import (
    RuntimeCreatorOperationAssembler,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", (False, True))
async def test_verified_execution_does_not_hide_pending_or_interrupted_result_cognition(
    interrupted: bool,
) -> None:
    original, result_root, creator, scene, task = (uuid7() for _ in range(5))
    digest = Digest.from_bytes(b"controlled result")
    acceptance = CreatorInputAcceptance(
        CreatorInteractionId(uuid7()),
        EvidenceId(uuid7()),
        OpportunityId(original),
        digest,
        digest,
        False,
    )

    @asynccontextmanager
    async def transaction(**_kwargs: object):
        yield SimpleNamespace(transaction=object())

    def opportunity(root: Any, disposition: str, purpose: str) -> SimpleNamespace:
        return SimpleNamespace(
            root_opportunity_id=root,
            current_opportunity_id=root,
            evidence_id=acceptance.evidence_id.value,
            scene_id=scene,
            purpose=purpose,
            disposition=disposition,
            reconsideration_no=0,
        )

    assembler = cast(Any, object.__new__(RuntimeCreatorOperationAssembler))
    assembler._factory = SimpleNamespace(unit_of_work=transaction)
    assembler._creator_party_id = creator
    assembler._opportunity = SimpleNamespace(
        operation_snapshot=AsyncMock(
            side_effect=[
                opportunity(original, "resolved", "consider_codex_task"),
                opportunity(
                    result_root,
                    "cancelled" if interrupted else "selected",
                    "consider_codex_result",
                ),
            ]
        )
    )
    assembler._evidence = SimpleNamespace(
        snapshot=AsyncMock(
            return_value=SimpleNamespace(
                codex_task_source_id=task,
                interaction_id=acceptance.interaction_id.value,
            )
        )
    )
    assembler._codex = SimpleNamespace(
        task_source=AsyncMock(return_value=SimpleNamespace(task_manifest_digest=digest))
    )
    assembler._interaction = SimpleNamespace(
        operation_acceptance=AsyncMock(return_value=acceptance)
    )
    assembler._cognition = SimpleNamespace(
        operation_snapshot=AsyncMock(
            side_effect=[
                CognitionOperationSnapshot("committed", None, "applied", 1),
                CognitionOperationSnapshot(
                    None if interrupted else "calling_model", None, None, None
                ),
            ]
        )
    )
    assembler._expression = SimpleNamespace(
        operation_snapshot=AsyncMock(
            side_effect=[
                ExpressionOperationSnapshot(
                    original, uuid7(), uuid7(), None, "codex_delegation", None, None
                ),
                None,
            ]
        )
    )
    assembler._effect = SimpleNamespace(
        by_action_intent=AsyncMock(
            return_value=SimpleNamespace(
                effect_id=uuid7(),
                status=EffectStatus.COMPLETED,
                observation_reason="CODEX-RESULT-VERIFIED",
                current_attempt_id=uuid7(),
                current_attempt_no=1,
                current_dispatch_state="settled",
                current_observation_id=uuid7(),
                observation_conclusion="completed",
                current_observation_reliability=None,
            )
        )
    )
    assembler._codex_executions = SimpleNamespace(
        execution_for_effect=AsyncMock(
            return_value=SimpleNamespace(
                result_opportunity_id=result_root,
                task_source_id=task,
                verification_id=uuid7(),
                execution_status="verified",
                model_id=None,
                sdk_identity=None,
                validator_id="codex.output-artifact.v1",
                source_tree_digest=digest,
                final_tree_digest=digest,
            )
        )
    )

    operation = await assembler.get(OpportunityId(original))
    assert operation.codex_execution.execution_status == "verified"
    wire = operation_wire(operation)
    if interrupted:
        assert operation.phase is CreatorOperationPhase.CODEX_FAILED
        assert wire["status"] == "failed"
        assert "waiting_for" not in wire
        assert (
            operation.codex_execution.result_processing_reason
            == "COGNITION-RUNTIME-INTERRUPTED"
        )
    else:
        assert operation.phase is CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE
        assert wire["status"] == "waiting"
        assert operation.codex_execution.result_processing_phase == "model_calling"
    assert (
        assembler._opportunity.operation_snapshot.await_args.kwargs[
            "root_opportunity_id"
        ]
        == result_root
    )
