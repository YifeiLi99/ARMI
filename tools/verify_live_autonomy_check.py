"""Explicit isolated two-stage model scenarios; never commits or sends messages."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_cognition.api import (
    AUTONOMY_CHECK_INSTRUCTIONS,
    CognitionSchemaDocument,
    autonomy_check_schema,
    parse_autonomy_check,
)
from armi_context.api import (
    ContextItemCandidate,
    ContextLayer,
    ContextRequirement,
    ContextSection,
    ContextSourceIdentity,
    ContextTrustClass,
    autonomy_check_items,
)
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    CandidateViolation,
    CredentialLocator,
    ModelResultStatus,
    ModelViolation,
    ProviderCallReceipt,
    ProviderMeterScope,
    load_price_catalog,
    provider_meter_scope,
)
from armi_kernel.contracts import Digest
from armi_local_control.configuration import EnvironmentFileCredentialPort
from armi_runtime.composition.candidate_validation_tool import build_candidate_validator
from armi_runtime.composition.model_adapter import create_model_adapter
from armi_runtime.composition.model_verification import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    build_request_bytes,
    checked_model_request,
    load_purpose_binding,
    model_response_candidate,
    parse_candidate,
)
from experiment_psychological_context import prepare_case, save

SCENARIOS = (
    ("answered_greeting", "刚刚互道早安,对方没有新问题,你也没有想补充的内容。", False),
    ("idle", "这段时间没有新事、开放关切或想做的事情,你此刻愿意安静待着。", False),
    (
        "ready_activity",
        "你正在写一小段散文,已经想到下一段的内容,现在可以继续写。",
        True,
    ),
    (
        "waiting_tool",
        "唯一的资料检索任务仍在执行,没有结果,也没有别的愿望或可推进事项。",
        False,
    ),
    ("own_wish", "没有外部任务,但你现在很想写一首关于秋风的短诗,思路已经浮现。", True),
)


def prepare_check(
    description: str, variant: int
) -> tuple[bytes, tuple[dict[str, object], ...]]:
    states: list[tuple[str, Any]] = [
        ("runtime_identity", {"subject_id": str(uuid7())}),
        ("current_purpose", {"purpose": "consider_autonomy_check"}),
        ("fixed_prompt", "约16岁少女的自然口吻,有自己的想法,对人友善,不强求每次发言。"),
        ("self", {"self_description": description}),
        (
            "mind",
            {"thoughts": [], "open_concerns_count": 0, "open_motivations_count": 0},
        ),
        ("mood", {"current": {"valence": 0, "arousal": 0, "dominance": 0}}),
        ("life_mode", {"mode": "awake", "available": True}),
        (
            "current_activities",
            {
                "activities": [
                    {
                        "status": "in_progress",
                        "goal": description,
                        "next_safe_step": description,
                        "waiting_condition": None,
                    }
                ]
            },
        ),
        (
            "current_life_opportunity",
            {
                "autonomy": {
                    "current_time": "2026-09-21T10:00:00+08:00",
                    "last_considered_at": None,
                    "outlet_state": "ready",
                }
            },
        ),
        (
            "recent_scene_turn",
            {
                "speaker": "creator",
                "text": ("早安", "在吗", "好啦", "等你忙完")[variant],
            },
        ),
        (
            "recent_scene_turn",
            {
                "speaker": "armi",
                "text": ("早呀", "在呢", "嗯好", "嗯,有结果再说")[variant],
            },
        ),
        (
            "capability_catalog",
            {
                "capabilities": [
                    {
                        "capability_kind": "internal_creation",
                        "availability_status": "available",
                        "authorization_status": "authorized",
                    }
                ]
            },
        ),
    ]
    items = [
        ContextItemCandidate(
            ContextSection.SELF,
            kind,
            ContextSourceIdentity(kind, uuid7(), 1),
            ContextTrustClass.SUBJECTIVE_STATE,
            "private",
            json.dumps(value, ensure_ascii=False),
            ContextRequirement.OPTIONAL,
            ContextLayer.TURN_TAIL,
            90,
        )
        for kind, value in states
    ]
    projected = autonomy_check_items(items, signalled_refs=frozenset())
    refs: tuple[dict[str, object], ...] = tuple(
        {
            "ref": f"ctx:{index}",
            "section": item.section.value,
            "item_kind": item.item_kind,
        }
        for index, item in enumerate(projected, 1)
    )
    compiled = rfc8785.dumps(
        {
            "schema_version": "armi.compiled-context.v3",
            "purpose": "consider_autonomy_check",
            "layers": [
                {
                    "items": [
                        {
                            "ref": ref["ref"],
                            "item_kind": item.item_kind,
                            "content": item.content,
                            "source": {
                                "kind": item.source.kind,
                                "reference": str(item.source.reference),
                                "version": item.source.version,
                            },
                        }
                        for item, ref in zip(projected, refs, strict=True)
                    ]
                }
            ],
        }
    )
    return compiled, refs


async def verify(
    root: Path, output: Path, *, checks_only: bool = False
) -> list[dict[str, Any]]:
    # Read only the selected locator. Source schema can be newer than the installed
    # environment; this experiment neither upgrades nor copies that environment.
    environment = cast(dict[str, Any], load_yaml_file(root / "environment.yaml"))
    locator = CredentialLocator.parse(
        environment["secret_locators"]["model.deepseek_api_key"]
    )
    credentials = EnvironmentFileCredentialPort(
        environment=dict(os.environ), secret_roots=((root / "secrets").resolve(),)
    )
    prices = load_price_catalog(Path("configs/provider-pricing.yaml"))
    rows: list[dict[str, Any]] = []
    for name, description, expected in SCENARIOS:
        for variant in range(4):
            group = output / f"{name}-{variant + 1}"
            group.mkdir()
            engage = False
            for stage in ("check", "execute"):
                if stage == "execute" and (not engage or checks_only):
                    break
                full = prepare_case(description) if stage == "execute" else None
                purpose = (
                    "consider_autonomous_life" if full else "consider_autonomy_check"
                )
                binding = replace(
                    load_purpose_binding(purpose),
                    provider="deepseek",
                    model_id="deepseek-flash",
                    api_base="https://api.deepseek.com",
                    credential_identity="armi.model.deepseek-api-key.v1",
                )
                if full:
                    compiled = full["compiled"]
                    refs = tuple(json.loads(full["request"])["included_context_refs"])
                    schema = full["schema"]
                else:
                    compiled, refs = prepare_check(description, variant)
                    schema = autonomy_check_schema()
                digest = Digest.from_bytes(compiled)
                request_bytes = build_request_bytes(
                    binding=binding,
                    compiled_context=compiled,
                    context_digest=digest,
                    base_subject_version=1,
                    base_state_epoch=1,
                    bundle_activation_id=uuid7(),
                    included_context_refs=refs,
                )
                adapter = create_model_adapter(
                    binding=binding,
                    credential_port=credentials,
                    locator=locator,
                    instructions=AUTONOMOUS_ACTIVITY_INSTRUCTIONS
                    if full
                    else AUTONOMY_CHECK_INSTRUCTIONS,
                    schema_name="armi_autonomous_activity_candidate_v11"
                    if full
                    else "armi_autonomy_check_candidate_v1",
                    candidate_schema=CognitionSchemaDocument(rfc8785.dumps(schema)),
                )
                receipts: dict[str, Any] = {}

                async def record(
                    receipt: ProviderCallReceipt,
                    receipts: dict[str, Any] = receipts,
                    receipt_path: Path = group / f"{stage}-calls.json",
                ) -> None:
                    receipts[receipt.call_id] = receipt.document()
                    receipt_path.write_text(
                        json.dumps(receipts, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                try:
                    with provider_meter_scope(
                        ProviderMeterScope(record, prices, purpose)
                    ):
                        request = checked_model_request(
                            binding=binding,
                            request_bytes=request_bytes,
                            context_digest=digest,
                            input_tokens=await adapter.tokenize(request_bytes),
                            prices=prices,
                        )
                        save(
                            group / f"{stage}-request.json",
                            adapter.request_evidence(request),
                        )
                        for attempt in range(1, 6):
                            started = time.perf_counter()
                            result = await adapter.invoke(request)
                            row: dict[str, Any] = {
                                "case": name,
                                "variant": variant + 1,
                                "stage": stage,
                                "attempt": attempt,
                                "latency_ms": round(
                                    (time.perf_counter() - started) * 1000
                                ),
                                "status": result.status.value,
                                "format_valid": False,
                                "error": result.error_code
                                or result.response_error_code,
                            }
                            if result.usage:
                                row.update(
                                    input_tokens=result.usage.input_tokens,
                                    output_tokens=result.usage.output_tokens,
                                    cached_input_tokens=result.usage.cached_input_tokens,
                                )
                            if result.response_bytes:
                                save(
                                    group / f"{stage}-response-{attempt}.json",
                                    result.response_bytes,
                                )
                            rows.append(row)
                            if (
                                result.status is not ModelResultStatus.SUCCEEDED
                                or result.response_error_code
                            ):
                                break
                            try:
                                if result.response_bytes is None:
                                    raise ModelViolation("MODEL-RESPONSE-EMPTY")
                                candidate = model_response_candidate(
                                    result.response_bytes,
                                    expected_version=binding.response_contract_version,
                                )
                                if full:
                                    parse_candidate(
                                        candidate,
                                        expected_version=binding.response_contract_version,
                                        purpose=purpose,
                                        allowed_context_refs=frozenset(
                                            str(r["ref"]) for r in refs
                                        ),
                                    )
                                else:
                                    engage = parse_autonomy_check(candidate).engage
                                    row.update(
                                        engage=engage,
                                        expected_engage=expected,
                                        expected_match=engage == expected,
                                    )
                                row["format_valid"] = True
                            except (CandidateViolation, ModelViolation) as error:
                                row["error"] = error.code
                                if error.code not in {
                                    "CANDIDATE-CONTRACT",
                                    "MODEL-RESPONSE-SCHEMA",
                                }:
                                    break
                                continue
                            if full:
                                validated = build_candidate_validator(
                                    full["validation"]
                                ).validate(
                                    rfc8785.dumps(candidate), bases=full["bases"]
                                )
                                row["owner_validation"] = validated.status.value
                                row["owner_error"] = validated.error_code
                            break
                finally:
                    await adapter.close()
                (output / "results.json").write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checks-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = asyncio.run(
        verify(args.environment_root, args.output, checks_only=args.checks_only)
    )
    checks = [r for r in rows if r["stage"] == "check"]
    print(
        json.dumps(
            {
                "checks": len(checks),
                "check_format_passes": sum(r["format_valid"] for r in checks),
                "max_check_input_tokens": max(
                    (r.get("input_tokens", 0) for r in checks), default=0
                ),
                "full_calls": sum(r["stage"] == "execute" for r in rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
