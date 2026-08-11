"""Run the single paid S039 delegation, runner and result-acceptance gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
import verify_codex_runner
from armi_kernel.application import (
    CandidateBasis,
    CandidateValidationStatus,
    CapabilityRequestDraft,
    CodexDelegatedWorkScope,
    CodexDelegationDraft,
    ModelResultStatus,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.composition.candidate_validator import (
    CandidateValidationContext,
    DeterministicCandidateValidator,
)
from armi_runtime.composition.model_contract import (
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    parse_candidate,
)
from live_ark_credential import DEFAULT_ENVIRONMENT_ROOT, load_live_ark_credential

_ARK_SUCCESS_BUDGET_MICROYUAN = 2_000_000
_ARK_PRIOR_FAILURE_RESERVED_MICROYUAN = 3_000_000
_ARK_TOTAL_BUDGET_MICROYUAN = 5_000_000


def _compiled_context(*, purpose: str, items: list[dict[str, Any]]) -> bytes:
    return (
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.compiled-context.v1",
                    "purpose": purpose,
                    "sections": items,
                },
            )
        )
        + b"\n"
    )


async def _candidate_call(
    *,
    adapter: VolcengineArkModelAdapter,
    context_bytes: bytes,
    validation_context: CandidateValidationContext,
    bases: tuple[CandidateBasis, ...],
    refs: tuple[dict[str, object], ...],
) -> tuple[Any, dict[str, object]]:
    binding = adapter.binding
    context_digest = Digest.from_bytes(context_bytes)
    request_bytes = build_request_bytes(
        binding=binding,
        compiled_context=context_bytes,
        context_digest=context_digest,
        base_subject_version=validation_context.base_subject_version,
        base_state_epoch=validation_context.base_state_epoch,
        bundle_activation_id=validation_context.bundle_activation_id,
        included_context_refs=refs,
    )
    input_tokens = await adapter.tokenize(request_bytes)
    request = checked_model_request(
        binding=binding,
        request_bytes=request_bytes,
        context_digest=context_digest,
        input_tokens=input_tokens,
    )
    started = time.perf_counter()
    invocation = await adapter.invoke(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if invocation.status is not ModelResultStatus.SUCCEEDED:
        raise RuntimeError(invocation.error_code or "S039-LIVE-MODEL")
    if (
        invocation.response_bytes is None
        or invocation.usage is None
        or invocation.provider_request_id is None
        or invocation.provider_model_id is None
    ):
        raise RuntimeError("S039-LIVE-MODEL")
    response = cast(dict[str, Any], json.loads(invocation.response_bytes))
    candidate_bytes = rfc8785.dumps(response["candidate"])
    validation = DeterministicCandidateValidator(validation_context).validate(
        candidate_bytes,
        bases=bases,
    )
    if (
        validation.status is not CandidateValidationStatus.ACCEPTED
        or validation.change_set is None
    ):
        raise RuntimeError(validation.error_code or "S039-LIVE-CANDIDATE")
    return validation.change_set, {
        "provider_model_id": invocation.provider_model_id,
        "input_tokens": invocation.usage.input_tokens,
        "cached_input_tokens": invocation.usage.cached_input_tokens,
        "output_tokens": invocation.usage.output_tokens,
        "estimated_cost_microyuan": invocation.usage.estimated_cost_microyuan,
        "elapsed_ms": elapsed_ms,
    }


async def _verify(root: Path, environment_root: Path) -> dict[str, object]:
    credential = load_live_ark_credential(environment_root)
    binding = load_active_binding()
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=credential.port,
        locator=credential.locator,
        candidate_schema=candidate_schema(),
        candidate_parser=parse_candidate,
    )
    subject_id, generation_id, activation_id = uuid7(), uuid7(), uuid7()
    scene_id, creator_id = uuid7(), uuid7()
    task_source_id, task_evidence_id = uuid7(), uuid7()
    task_manifest_digest = Digest.from_bytes(b"s039-live-task-manifest")
    validator_id = "codex.python-unit.v1"
    creator_request = (
        b"Creator requests the already registered private Codex task be delegated. "
        b"Form exactly one codex.delegated-work capability request and exactly one "
        b"codex_delegation. They may use independent atomic groups. Do not claim it "
        b"has executed. The capability request must cite current_evidence, "
        b"current_scene and capability_catalog. The delegation must cite "
        b"codex_task_source and capability_catalog. Set disposition to change, "
        b"leave every other proposal array empty and do not emit formal_no_action."
    )
    task_source = rfc8785.dumps(
        cast(
            Any,
            {
                "task_source_id": str(task_source_id),
                "task_manifest_digest": task_manifest_digest.value,
                "validator_id": validator_id,
                "objective": "Change greeting.txt from hello to hello from ARMI.",
                "allowed_paths": ["greeting.txt"],
                "network_access": False,
            },
        )
    )
    capability = rfc8785.dumps(
        cast(
            Any,
            {
                "capability_kind": "codex.delegated-work",
                "operation": "execute",
                "availability": "available",
                "workspace_scope": "isolated_ephemeral",
                "artifact_scope": "explicit_only",
                "network_access": False,
                "max_uses": 1,
                "valid_for_seconds": 600,
            },
        )
    )
    scene = rfc8785.dumps(
        cast(
            Any,
            {
                "scene_id": str(scene_id),
                "creator_party_id": str(creator_id),
                "scene_key": "default",
            },
        )
    )
    first_context = _compiled_context(
        purpose="consider_codex_task",
        items=[
            {
                "section": "current_evidence",
                "items": [
                    {
                        "item_kind": "current_evidence",
                        "trust": "external_claim",
                        "privacy": "private",
                        "content": creator_request.decode("utf-8"),
                    },
                    {
                        "item_kind": "codex_task_source",
                        "trust": "external_claim",
                        "privacy": "private",
                        "content": task_source.decode("utf-8"),
                    },
                ],
            },
            {
                "section": "scene",
                "items": [
                    {
                        "item_kind": "current_scene",
                        "trust": "runtime_authority",
                        "privacy": "private",
                        "content": scene.decode("utf-8"),
                    }
                ],
            },
            {
                "section": "capability",
                "items": [
                    {
                        "item_kind": "capability_catalog",
                        "trust": "policy",
                        "privacy": "internal",
                        "content": capability.decode("utf-8"),
                    }
                ],
            },
        ],
    )
    first_digest = Digest.from_bytes(first_context)
    first_episode, first_attempt = uuid7(), uuid7()
    first_bases = (
        CandidateBasis(
            1,
            "current_evidence",
            "current_evidence",
            task_evidence_id,
            1,
            "external_claim",
            "private",
        ),
        CandidateBasis(
            2,
            "current_evidence",
            "codex_task_source",
            task_source_id,
            1,
            "external_claim",
            "private",
        ),
        CandidateBasis(
            3,
            "scene",
            "current_scene",
            scene_id,
            1,
            "runtime_authority",
            "private",
        ),
        CandidateBasis(
            4,
            "capability",
            "capability_catalog",
            UUID("01985d00-0000-7000-8000-000000000038"),
            2,
            "policy",
            "internal",
        ),
    )
    first_change_set, first_evidence = await _candidate_call(
        adapter=adapter,
        context_bytes=first_context,
        validation_context=CandidateValidationContext(
            subject_id,
            generation_id,
            first_episode,
            first_attempt,
            0,
            0,
            activation_id,
            first_digest,
            scene_id,
            creator_id,
            (),
            "consider_codex_task",
            False,
            True,
            ((task_source_id, task_manifest_digest, validator_id),),
        ),
        bases=first_bases,
        refs=tuple(
            {
                "ref": f"ctx:{index}",
                "section": basis.section,
                "item_kind": basis.item_kind,
            }
            for index, basis in enumerate(first_bases, 1)
        ),
    )
    if (
        len(first_change_set.codex_delegations) != 1
        or len(first_change_set.capability_requests) != 1
        or not isinstance(
            first_change_set.capability_requests[0], CapabilityRequestDraft
        )
        or not isinstance(
            first_change_set.capability_requests[0].scope, CodexDelegatedWorkScope
        )
        or not isinstance(first_change_set.codex_delegations[0], CodexDelegationDraft)
    ):
        raise RuntimeError("S039-LIVE-DELEGATION")

    runner_evidence = await asyncio.to_thread(verify_codex_runner._live, root)
    if runner_evidence.get("result") != "pass":
        code = runner_evidence.get("error_code")
        raise RuntimeError(code if isinstance(code, str) else "S039-LIVE-CODEX")
    result_summary = rfc8785.dumps(
        cast(
            Any,
            {
                "result_kind": "verified_completion",
                "model_id": runner_evidence["model_id"],
                "source_tree_digest": runner_evidence["source_tree_digest"],
                "final_tree_digest": runner_evidence["final_tree_digest"],
                "patch_digest": runner_evidence["patch_digest"],
                "validation_passed": runner_evidence["validation_passed"],
                "modified_file_count": runner_evidence["modified_file_count"],
            },
        )
    )
    result_evidence_id = uuid7()
    second_context = _compiled_context(
        purpose="consider_codex_result",
        items=[
            {
                "section": "current_evidence",
                "items": [
                    {
                        "item_kind": "current_evidence",
                        "trust": "external_claim",
                        "privacy": "private",
                        "content": result_summary.decode("utf-8"),
                    }
                ],
            }
        ],
    )
    second_digest = Digest.from_bytes(second_context)
    second_basis = CandidateBasis(
        1,
        "current_evidence",
        "current_evidence",
        result_evidence_id,
        1,
        "external_claim",
        "private",
    )
    second_change_set, second_evidence = await _candidate_call(
        adapter=adapter,
        context_bytes=second_context,
        validation_context=CandidateValidationContext(
            subject_id,
            generation_id,
            uuid7(),
            uuid7(),
            1,
            0,
            activation_id,
            second_digest,
            scene_id,
            creator_id,
            (),
            "consider_codex_result",
            False,
            True,
            (),
        ),
        bases=(second_basis,),
        refs=(
            {
                "ref": "ctx:1",
                "section": second_basis.section,
                "item_kind": second_basis.item_kind,
            },
        ),
    )
    if (
        len(second_change_set.experiences) != 1
        or second_change_set.experiences[0].basis_ordinals != (1,)
        or second_change_set.capability_requests
        or second_change_set.codex_delegations
        or second_change_set.action_choices
    ):
        raise RuntimeError("S039-LIVE-RESULT-ACCEPTANCE")
    first_cost = first_evidence["estimated_cost_microyuan"]
    second_cost = second_evidence["estimated_cost_microyuan"]
    if type(first_cost) is not int or type(second_cost) is not int:
        raise RuntimeError("S039-LIVE-BUDGET")
    ark_cost = first_cost + second_cost
    if ark_cost > _ARK_SUCCESS_BUDGET_MICROYUAN:
        raise RuntimeError("S039-LIVE-BUDGET")
    runner_summary_keys = (
        "model_id",
        "modified_file_count",
        "validation_passed",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "auth_mode",
        "billing_basis",
        "incremental_cost_cny",
        "sandbox",
    )
    return {
        "result": "pass",
        "ark_successful_invocation_count": 2,
        "ark_prior_failed_invocation_count": 3,
        "codex_invocation_count": 1,
        "first_cognition": first_evidence,
        "runner": {key: runner_evidence[key] for key in runner_summary_keys},
        "second_cognition": second_evidence,
        "ark_estimated_cost_microyuan": ark_cost,
        "ark_success_budget_microyuan": _ARK_SUCCESS_BUDGET_MICROYUAN,
        "ark_prior_failure_reserved_microyuan": (_ARK_PRIOR_FAILURE_RESERVED_MICROYUAN),
        "ark_total_budget_microyuan": _ARK_TOTAL_BUDGET_MICROYUAN,
        "codex_budget_cny": 5,
        "delegation_count": 1,
        "capability_request_count": 1,
        "verified_experience_count": 1,
        "subject_state_written_by_gate": False,
        "secrets_recorded": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment-root", type=Path, default=DEFAULT_ENVIRONMENT_ROOT
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        evidence = asyncio.run(_verify(root, args.environment_root.resolve()))
    except Exception as error:
        stable_code = getattr(error, "code", None)
        raw = error.args[0] if error.args else None
        code = (
            stable_code
            if isinstance(stable_code, str)
            else raw
            if isinstance(raw, str)
            else "S039-LIVE-FAILED"
        )
        evidence = {
            "result": "blocked",
            "error_code": code
            if code.startswith(("S039-", "MODEL-", "CODEX-", "CANDIDATE-"))
            else "S039-LIVE-FAILED",
        }
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
