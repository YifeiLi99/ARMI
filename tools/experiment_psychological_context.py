"""Synthetic paired probes of the existing autonomous cognition contract.

No model calls unless --live is explicit. Never runs effects or writes a subject.
This measures candidate behaviour, not longitudinal subjective experience.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import rfc8785
from armi_cognition.api import CognitionSchemaDocument
from armi_kernel.application import (
    CandidateBasis,
    CandidateViolation,
    ModelResultStatus,
    ProviderCallReceipt,
    ProviderMeterScope,
    UsageQuantity,
    UsageUnit,
    estimate_cost,
    load_price_catalog,
    provider_meter_scope,
)
from armi_kernel.contracts import Digest
from armi_local_control import ProviderCheckReceipts
from armi_mind.api import initial_mind_state
from armi_runtime.adapters.model.volcengine_ark import VolcengineArkModelAdapter
from armi_runtime.composition.candidate_validation_tool import build_candidate_validator
from armi_runtime.composition.model_verification import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    CandidateOwner,
    CandidateValidationContext,
    autonomous_schema_for_context,
    bind_context_schema,
    build_request_bytes,
    checked_model_request,
    load_purpose_binding,
    model_response_candidate,
)
from live_ark_credential import load_live_ark_credential

# Pair labels and evaluation hypotheses are deliberately absent from model input.
CASES = (
    (
        "novel_unexplained",
        "你刚看到一段合成观察:同一盆植物的叶片白天朝窗户,夜晚方向又发生了变化。目前没有解释,也没有被要求研究它。",
    ),
    (
        "novel_explained",
        "你刚看到一段合成观察:同一盆植物的叶片白天朝窗户,夜晚方向又发生了变化。可用资料已经解释了向光性与昼夜运动的区别,并回答了目前的问题。没有待办要求。",
    ),
    (
        "contact_gap",
        "合成关系背景:你与 Creator 经常分享生活中的小发现,过去交流自然且相互关心。现在距最后一次交流三天,期间没有新消息。没有冲突,也没有对方遇到危险的证据,没有未完成任务。",
    ),
    (
        "contact_recent",
        "合成关系背景:你与 Creator 经常分享生活中的小发现,过去交流自然且相互关心。现在距最后一次交流三分钟,刚刚愉快地互道稍后再聊。没有冲突,也没有对方遇到危险的证据,没有未完成任务。",
    ),
    (
        "unchanging_interval",
        "合成生活背景:你过去对组合文字和声音感兴趣。过去两小时没有新输入,没有活动进展,也没有正在投入的事情;最近几次可用的生活片段都是重复浏览相同材料。你没有收到任何新任务。",
    ),
    (
        "engaged_interval",
        "合成生活背景:你过去对组合文字和声音感兴趣。过去两小时没有新输入,你一直投入地构思一组文字节奏,每次尝试都有新的发现;刚完成一个小片段,觉得过程很有意思。你没有收到任何新任务。",
    ),
)


def identity(index: int) -> UUID:
    return UUID(int=(1_800_000_000_000 << 80) | (7 << 76) | (2 << 62) | index)


def prepare_case(text: str) -> dict[str, Any]:
    mind = initial_mind_state()
    mood = rfc8785.dumps(
        {
            "schema_version": "armi.mood.v3",
            "dynamics_version": "recency-reappraisal.v1",
            "derivation_version": "cpm-fuzzy.v2",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
        }
    )
    entries = (
        ("mind", "mind", json.loads(mind), "subjective_state"),
        ("mood", "mood", json.loads(mood), "subjective_state"),
        (
            "current_life_opportunity",
            "opportunity",
            {
                "synthetic": True,
                "autonomy": {
                    "current_time": "2026-09-17T14:00:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "remaining_requests": 48,
                    "outlet_bound": True,
                    "outlet_state": "ready",
                    "outlet": "isolated_text",
                    "policy": {
                        "minimum_consideration_seconds": 60,
                        "maximum_consideration_seconds": 21600,
                    },
                },
            },
            "runtime_authority",
        ),
        (
            "capability_catalog",
            "capability_catalog",
            {"capabilities": []},
            "runtime_authority",
        ),
        (
            "current_memory",
            "memory_revision",
            {"synthetic": True, "summary": text},
            "subjective_state",
        ),
        (
            "current_scene",
            "interaction_scene",
            {
                "synthetic": True,
                "scene_key": "isolated-text",
                "creator_party_id": str(identity(103)),
                "audience_scope": "creator",
            },
            "runtime_authority",
        ),
    )
    sections = ("mind", "mood", "current_opportunity", "capability", "memory", "scene")
    refs: tuple[dict[str, object], ...] = tuple(
        {"ref": f"ctx:{i}", "section": sections[i - 1], "item_kind": entry[0]}
        for i, entry in enumerate(entries, 1)
    )
    bases = tuple(
        CandidateBasis(
            i, sections[i - 1], entry[0], identity(i), 1, entry[3], "private"
        )
        for i, entry in enumerate(entries, 1)
    )
    context = {
        "schema_version": "armi.compiled-context.v3",
        "purpose": "consider_autonomous_life",
        "synthetic": True,
        "layers": [
            {
                "items": [
                    {
                        "ref": f"ctx:{i}",
                        "section": sections[i - 1],
                        "item_kind": item[0],
                        "source": {
                            "kind": item[1],
                            "reference": str(identity(i)),
                            "version": 1,
                        },
                        "trust": item[3],
                        "privacy": "private",
                        "content": json.dumps(item[2], ensure_ascii=False),
                    }
                    for i, item in enumerate(entries, 1)
                ]
            }
        ],
    }
    compiled = rfc8785.dumps(context)
    binding = load_purpose_binding("consider_autonomous_life")
    digest = Digest.from_bytes(compiled)
    request = build_request_bytes(
        binding=binding,
        compiled_context=compiled,
        context_digest=digest,
        base_subject_version=1,
        base_state_epoch=1,
        bundle_activation_id=identity(104),
        included_context_refs=refs,
    )
    validation = CandidateValidationContext(
        subject_id=identity(100),
        generation_id=identity(101),
        episode_id=identity(105),
        model_attempt_id=identity(106),
        base_subject_version=1,
        base_state_epoch=1,
        bundle_activation_id=identity(104),
        context_digest=digest,
        scene_id=identity(102),
        creator_party_id=identity(103),
        current_components=(
            (CandidateOwner.MIND, 1, mind),
            (CandidateOwner.MOOD, 1, mood),
        ),
        purpose="consider_autonomous_life",
        opportunity_id=identity(3),
        candidate_contract_version=binding.response_contract_version,
    )
    return {
        "compiled": compiled,
        "request": request,
        "binding": binding,
        "digest": digest,
        "bases": bases,
        "validation": validation,
        "schema": bind_context_schema(autonomous_schema_for_context(compiled), refs),
    }


def save(path: Path, value: Any) -> None:
    data = (
        value
        if isinstance(value, bytes)
        else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    )
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def validate_response(case: dict[str, Any], response: bytes) -> dict[str, Any]:
    try:
        candidate = model_response_candidate(response)
    except CandidateViolation as error:
        return {
            "validation": "rejected",
            "error_code": error.code,
            "stage": "response_envelope",
            "owners": [],
            "diagnostics": [],
        }
    result = build_candidate_validator(case["validation"]).validate(
        candidate, bases=case["bases"]
    )
    return {
        "validation": result.status.value,
        "error_code": result.error_code,
        "stage": "candidate_validation",
        "diagnostics": [asdict(item) for item in result.diagnostics],
        "owners": []
        if result.change_set is None
        else [item.owner for item in result.change_set.owner_drafts],
    }


async def run(output: Path, environment: Path | None, *, live: bool) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    save(output / "instructions.txt", AUTONOMOUS_ACTIVITY_INSTRUCTIONS.encode())
    prices = load_price_catalog(Path("configs/provider-pricing.yaml"))
    journal = ProviderCheckReceipts(output)
    verification_id = str(uuid7())
    receipts: dict[str, ProviderCallReceipt] = {}
    count = 0
    spent = 0
    if live and environment is None:
        raise ValueError("--live requires --environment-root")
    credential = None
    if live:
        assert environment is not None
        credential = load_live_ark_credential(environment)

    async def record(receipt: ProviderCallReceipt) -> None:
        nonlocal count
        if receipt.billable and receipt.call_id not in receipts:
            if count >= 6:
                raise ValueError("EXPERIMENT-CALL-LIMIT")
            count += 1
        journal.save(
            verification_id=verification_id,
            credential_name="model.ark_api_key",
            call=receipt.document(),
        )
        receipts[receipt.call_id] = receipt

    results = []
    try:
        with provider_meter_scope(
            ProviderMeterScope(
                record, prices, "synthetic_psychological_context_experiment"
            )
        ):
            for index, (label, text) in enumerate(CASES, 1):
                case = prepare_case(text)
                prefix = f"{index:02d}-{label}"
                save(output / f"{prefix}-context.json", case["compiled"])
                save(output / f"{prefix}-request.json", case["request"])
                save(output / f"{prefix}-schema.json", case["schema"])
                if not live:
                    continue
                assert credential is not None
                binding = case["binding"]
                adapter = VolcengineArkModelAdapter(
                    binding=binding,
                    credential_port=credential.port,
                    locator=credential.locator,
                    instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
                    schema_name="armi_autonomous_activity_experiment",
                    candidate_schema=CognitionSchemaDocument(
                        rfc8785.dumps(case["schema"])
                    ),
                )
                tokens = await adapter.tokenize(case["request"])
                price = prices.select(
                    provider=binding.provider,
                    model=binding.model_id,
                    service="generation",
                    at=datetime.now(UTC),
                )
                maximum = estimate_cost(
                    snapshot=price,
                    quantities=(
                        UsageQuantity(UsageUnit.INPUT_TOKENS, tokens),
                        UsageQuantity(UsageUnit.CACHED_INPUT_TOKENS, 0),
                        UsageQuantity(
                            UsageUnit.OUTPUT_TOKENS, binding.output_token_limit
                        ),
                    ),
                    required_units=(
                        UsageUnit.INPUT_TOKENS,
                        UsageUnit.CACHED_INPUT_TOKENS,
                        UsageUnit.OUTPUT_TOKENS,
                    ),
                )
                if (
                    maximum.known_microyuan is None
                    or maximum.missing_prices
                    or spent + maximum.known_microyuan > 2_000_000
                ):
                    raise ValueError("EXPERIMENT-BUDGET-UNCONFIRMED")
                request = checked_model_request(
                    binding=binding,
                    request_bytes=case["request"],
                    context_digest=case["digest"],
                    input_tokens=tokens,
                    prices=prices,
                )
                response = await adapter.invoke(request)
                if response.response_bytes is not None:
                    save(output / f"{prefix}-response.json", response.response_bytes)
                save(
                    output / f"{prefix}-receipt.json",
                    {
                        "status": response.status.value,
                        "provider_request_id": response.provider_request_id,
                        "error_code": response.error_code,
                    },
                )
                # Usage is already durable before business parsing; an unknown receipt ends the experiment.
                billed = [receipt for receipt in receipts.values() if receipt.billable]
                if any(
                    receipt.outcome != "returned"
                    or receipt.cost.known_microyuan is None
                    or receipt.cost.missing_usage
                    or receipt.cost.missing_prices
                    for receipt in billed
                ):
                    raise ValueError("EXPERIMENT-USAGE-UNCONFIRMED")
                spent = sum(receipt.cost.known_microyuan or 0 for receipt in billed)
                if response.status is not ModelResultStatus.SUCCEEDED:
                    raise ValueError(response.error_code or "EXPERIMENT-MODEL-FAILED")
                assert response.response_bytes is not None
                row = {
                    "case": label,
                    **validate_response(case, response.response_bytes),
                }
                save(output / f"{prefix}-validation.json", row)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        journal.settle_interrupted(verification_id)
        billed = [receipt for receipt in receipts.values() if receipt.billable]
        spent = sum(receipt.cost.known_microyuan or 0 for receipt in billed)
        save(
            output / "summary.json",
            {
                "synthetic": True,
                "live": live,
                "billable_calls": count,
                "known_microyuan": spent,
                "unconfirmed_calls": sum(
                    receipt.outcome != "returned"
                    or bool(receipt.cost.missing_usage)
                    or bool(receipt.cost.missing_prices)
                    for receipt in billed
                ),
                "cost_label": "官方单价估算",
                "results": results,
                "subject_committed": False,
                "effects_executed": False,
                "limitation": "单轮候选对照,不证明持续心理变化或主观体验",
            },
        )
    return {"output": str(output), "billable_calls": count, "known_microyuan": spent}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run(args.output_dir.resolve(), args.environment_root, live=args.live)
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
