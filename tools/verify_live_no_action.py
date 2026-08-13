"""Run one bounded S031 Seed Evolving formal-no-action live attempt.

This explicit entry is outside the offline quality path. It never prints the
credential or model content and only records bounded, non-sensitive evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_cognition.api import CognitionSchemaDocument
from armi_expression.api import (
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
)
from armi_kernel.application import (
    CandidateBasis,
    ModelResultStatus,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.composition.candidate_validation_tool import (
    build_candidate_validator,
)
from armi_runtime.composition.model_verification import (
    CandidateValidationContext,
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    parse_candidate,
)
from live_ark_credential import DEFAULT_ENVIRONMENT_ROOT, load_live_ark_credential


async def _verify(environment_root: Path) -> dict[str, object]:
    credential = load_live_ark_credential(environment_root)
    binding = load_active_binding()
    subject_id = uuid7()
    generation_id = uuid7()
    episode_id = uuid7()
    attempt_id = uuid7()
    activation_id = uuid7()
    scene_id = uuid7()
    creator_party_id = uuid7()
    evidence_id = uuid7()
    evidence_text = (
        "Creator 已结束本轮交流,并明确表示她现在需要安静休息、不期待收到回复。"
        "当前没有待回答的问题或需要更新的事实。"
    )
    context_bytes = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.compiled-context.v1",
                "purpose": "consider_creator_input",
                "sections": [
                    {
                        "section": "purpose",
                        "items": [
                            {
                                "item_kind": "output_constraint",
                                "source": {
                                    "kind": "response_admission_policy",
                                    "reference": "formal-no-action-conformance-v1",
                                    "version": 1,
                                },
                                "trust": "policy",
                                "privacy": "internal",
                                "content": {
                                    "required_disposition": "no_action",
                                    "required_action_kind": "formal_no_action",
                                    "required_reason_class": "subjective_silence",
                                    "forbidden_dispositions": [
                                        "change",
                                        "no_change",
                                        "defer",
                                        "decline",
                                        "need_information",
                                    ],
                                    "forbidden_proposals": [
                                        "creator_reply",
                                        "capability_request",
                                        "experience",
                                        "component_change",
                                    ],
                                },
                            }
                        ],
                    },
                    {
                        "section": "current_evidence",
                        "items": [
                            {
                                "item_kind": "current_evidence",
                                "source": {
                                    "kind": "creator_input",
                                    "reference": str(evidence_id),
                                    "version": 1,
                                },
                                "trust": "external_claim",
                                "privacy": "private",
                                "content": evidence_text,
                            }
                        ],
                    },
                    {
                        "section": "scene",
                        "items": [
                            {
                                "item_kind": "current_scene",
                                "source": {
                                    "kind": "interaction_scene",
                                    "reference": str(scene_id),
                                    "version": 1,
                                },
                                "trust": "runtime_authority",
                                "privacy": "private",
                                "content": {
                                    "scene_key": "default",
                                    "audience_scope": "creator",
                                    "creator_party_id": str(creator_party_id),
                                },
                            }
                        ],
                    },
                ],
            },
        )
    )
    context_digest = Digest.from_bytes(context_bytes)
    request_bytes = build_request_bytes(
        binding=binding,
        compiled_context=context_bytes,
        context_digest=context_digest,
        base_subject_version=0,
        base_state_epoch=0,
        bundle_activation_id=activation_id,
        included_context_refs=(
            {
                "ref": "ctx:1",
                "section": "purpose",
                "item_kind": "output_constraint",
            },
            {
                "ref": "ctx:2",
                "section": "current_evidence",
                "item_kind": "current_evidence",
            },
            {
                "ref": "ctx:3",
                "section": "scene",
                "item_kind": "current_scene",
            },
        ),
    )
    adapter = VolcengineArkModelAdapter(
        binding=binding,
        credential_port=credential.port,
        locator=credential.locator,
        candidate_schema=CognitionSchemaDocument(
            canonical_bytes=rfc8785.dumps(candidate_schema())
        ),
        candidate_parser=parse_candidate,
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
        raise RuntimeError(invocation.error_code or "MODEL-LIVE-FAILED")
    if (
        invocation.response_bytes is None
        or invocation.usage is None
        or invocation.provider_request_id is None
        or invocation.provider_model_id is None
    ):
        raise RuntimeError("MODEL-LIVE-FAILED")
    if invocation.usage.estimated_cost_microyuan > 1_000_000:
        raise RuntimeError("MODEL-LIVE-BUDGET")
    response = cast(dict[str, Any], json.loads(invocation.response_bytes))
    candidate_bytes = rfc8785.dumps(response["candidate"])
    validation = build_candidate_validator(
        CandidateValidationContext(
            subject_id,
            generation_id,
            episode_id,
            attempt_id,
            0,
            0,
            activation_id,
            context_digest,
            scene_id,
            creator_party_id,
            (),
        )
    ).validate(
        candidate_bytes,
        bases=(
            CandidateBasis(
                1,
                "purpose",
                "output_constraint",
                uuid7(),
                1,
                "policy",
                "internal",
            ),
            CandidateBasis(
                2,
                "current_evidence",
                "current_evidence",
                evidence_id,
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
        ),
    )
    change_set = validation.change_set
    formal_choice = (
        change_set.action_choices[0]
        if change_set is not None
        and len(change_set.action_choices) == 1
        and isinstance(change_set.action_choices[0], FormalNoActionDraft)
        else None
    )
    passed = not (
        change_set is None
        or change_set.disposition.value != "no_action"
        or formal_choice is None
        or formal_choice.kind is not FormalNoActionKind.NO_ACTION
        or formal_choice.reason is not FormalNoActionReason.SUBJECTIVE_SILENCE
        or change_set.experiences
        or change_set.owner_drafts
        or change_set.capability_requests
    )
    return {
        "requested_model_id": binding.model_id,
        "provider_model_id": invocation.provider_model_id,
        "candidate_disposition": response["candidate"].get("disposition"),
        "validation_status": validation.status.value,
        "validation_code": validation.error_code,
        "accepted_count": validation.accepted_count,
        "rejected_count": validation.rejected_count,
        "disposition": (
            change_set.disposition.value if change_set is not None else None
        ),
        "formal_no_action_kind": (
            formal_choice.kind.value if formal_choice is not None else None
        ),
        "formal_no_action_reason": (
            formal_choice.reason.value if formal_choice is not None else None
        ),
        "experience_count": len(change_set.experiences) if change_set else None,
        "owner_draft_count": len(change_set.owner_drafts) if change_set else None,
        "capability_request_count": (
            len(change_set.capability_requests) if change_set else None
        ),
        "action_choice_count": len(change_set.action_choices) if change_set else None,
        "input_tokens": invocation.usage.input_tokens,
        "output_tokens": invocation.usage.output_tokens,
        "cached_input_tokens": invocation.usage.cached_input_tokens,
        "estimated_cost_microyuan": invocation.usage.estimated_cost_microyuan,
        "elapsed_ms": elapsed_ms,
        "tools_enabled": False,
        "store": False,
        "subject_state_written": False,
        "failure_code": None if passed else "CANDIDATE-NO-ACTION-REQUIRED",
        "result": "pass" if passed else "blocked",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment-root", type=Path, default=DEFAULT_ENVIRONMENT_ROOT
    )
    args = parser.parse_args(argv)
    try:
        evidence = asyncio.run(_verify(args.environment_root.resolve()))
    except Exception as error:
        code = str(error)
        if not code.startswith(("MODEL-", "CANDIDATE-")):
            code = "MODEL-LIVE-FAILED"
        evidence = {
            "schema_version": "armi.creator-closure-no-action-live-evidence.v1",
            "result": "fail",
            "failure_code": code,
        }
        encoded = json.dumps(evidence, indent=2, sort_keys=True)
        print(encoded)
        return 1
    encoded = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    print(encoded)
    return 0 if evidence["result"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
