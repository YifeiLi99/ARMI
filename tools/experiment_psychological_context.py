"""Synthetic paired probes and an in-memory Mind trajectory experiment.

No model calls unless --live is explicit. Never runs effects or writes a subject.
This measures candidates and Owner transformations, not subjective experience.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
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
from armi_mind.api import (
    MIND_APPRAISAL_INSTRUCTIONS,
    CandidateMindDraft,
    MindAppraisal,
    MindHead,
    MindViolation,
    evaluate_motivation,
    initial_mind_state,
    mind_context_items,
    mind_motivation_projection,
    mind_signals,
    prepare_mind_change,
    project_motivation,
)
from armi_mood.api import (
    MOOD_APPRAISAL_INSTRUCTIONS,
    NewMoodAppraisalCommand,
    preview_appraisal,
    semantic_appraisal_from_command,
)
from armi_runtime.adapters.model.compatible import CompatibleStructuredTransport
from armi_runtime.adapters.model.model_clients import ModelClients
from armi_runtime.composition.candidate_validation_tool import build_candidate_validator
from armi_runtime.composition.config_assets import runtime_config_path
from armi_runtime.composition.model_adapter import create_model_adapter
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
from live_ark_credential import load_live_text_credential
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


def prepare_case(
    text: str, *, head: MindHead | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime(2026, 9, 17, 6, tzinfo=UTC)
    head = head or MindHead(identity(1), 1, initial_mind_state())
    mind = head.canonical_state
    psychological = mind_context_items(
        mind,
        revision_id=head.current_revision_id,
        version=head.version,
        as_of=now,
        purpose="consider_autonomous_life",
        signals=tuple(s for s in mind_signals(mind) if s.eligible_at <= now),
    )
    mood = rfc8785.dumps(
        {
            "schema_kind": "armi.mood",
            "dynamics_method": "recency-reappraisal",
            "derivation_method": "cpm-fuzzy",
            "home_base": {"valence": 0, "arousal": 0, "dominance": 0},
        }
    )
    entries = (
        ("mind", "mind", json.loads(psychological[0].content), "subjective_state"),
        ("mood", "mood", json.loads(mood), "subjective_state"),
        (
            "current_life_opportunity",
            "opportunity",
            {
                "synthetic": True,
                "autonomy": {
                    "current_time": now.isoformat(),
                    "timezone": "Asia/Shanghai",
                    "outlet_bound": True,
                    "outlet_state": "ready",
                    "outlet": "isolated_text",
                    "policy": {"enabled": True, "outlet": "creator_web"},
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
    entries += tuple(
        (item.item_kind, item.source_kind, json.loads(item.content), "subjective_state")
        for item in psychological[1:]
    )
    sections = (
        "mind",
        "mood",
        "current_opportunity",
        "capability",
        "memory",
        "scene",
    ) + ("mind",) * (len(psychological) - 1)
    sources = [
        (head.current_revision_id, head.version),
        *((identity(i), 1) for i in range(2, 7)),
        *((item.source_ref, item.source_version) for item in psychological[1:]),
    ]
    refs: tuple[dict[str, object], ...] = tuple(
        {"ref": f"ctx:{i}", "section": sections[i - 1], "item_kind": entry[0]}
        for i, entry in enumerate(entries, 1)
    )
    bases = tuple(
        CandidateBasis(
            i, sections[i - 1], entry[0], *sources[i - 1], entry[3], "private"
        )
        for i, entry in enumerate(entries, 1)
    )
    context = {
        "schema_kind": "armi.compiled-context",
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
                            "reference": str(sources[i - 1][0]),
                            "version": sources[i - 1][1],
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
        episode_id=identity(105),
        model_attempt_id=identity(106),
        base_subject_version=1,
        base_state_epoch=1,
        bundle_activation_id=identity(104),
        context_digest=digest,
        scene_id=identity(102),
        creator_party_id=identity(103),
        current_components=(
            (CandidateOwner.MIND, head.version, mind),
            (CandidateOwner.MOOD, 1, mood),
        ),
        purpose="consider_autonomous_life",
        opportunity_id=identity(3),
        candidate_contract_kind=binding.response_contract_kind,
    )
    return {
        "compiled": compiled,
        "request": request,
        "binding": binding,
        "digest": digest,
        "bases": bases,
        "validation": validation,
        "schema": bind_context_schema(autonomous_schema_for_context(compiled), refs),
        "now": now,
        "head": head,
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


class PsychologicalEvaluation(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", strict=True)
    mind: tuple[MindAppraisal, ...] = Field(max_length=4)
    mood: NewMoodAppraisalCommand | None


class SchemaProbe(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", strict=True)
    marker: Literal["valid"]
    seconds: int = Field(ge=60, le=21600)


def appraisal_case(text: str) -> dict[str, Any]:
    case = prepare_case(text)
    case["schema"] = PsychologicalEvaluation.model_json_schema()
    case["request"] = rfc8785.dumps(
        {
            "schema_kind": "armi.model-request",
            "compiled_context": {
                "purpose": "consider_autonomous_life",
                "layers": [
                    {"items": [{"item_kind": "current_evidence", "content": text}]}
                ],
            },
            "included_context_refs": [{"ref": "ctx:1"}],
        }
    )
    return case


def validate_appraisal_response(
    case: dict[str, Any], response: bytes
) -> dict[str, Any]:
    try:
        value = PsychologicalEvaluation.model_validate_json(
            json.dumps(model_response_candidate(response))
        )
        seen: set[tuple[str, str]] = set()
        projections = []
        at = datetime(2026, 9, 17, tzinfo=UTC)
        for assessment in value.mind:
            key = (assessment.object_ref, assessment.desired_outcome)
            if key in seen:
                raise ValueError("MIND-APPRAISAL-DUPLICATE")
            seen.add(key)
            state = evaluate_motivation(
                assessment, references={"ctx:1": "synthetic-object"}, at=at
            )
            projections.append(
                {
                    "assessment": assessment.model_dump(mode="json"),
                    "trajectory": [
                        asdict(
                            project_motivation(state, at=at + timedelta(minutes=minute))
                        )
                        for minute in (0, 30, 120)
                    ],
                }
            )
        mood = None
        if value.mood is not None:
            mood = preview_appraisal(semantic_appraisal_from_command(value.mood))
        return {
            "validation": "accepted",
            "mind": projections,
            "mood_assessment": None
            if value.mood is None
            else value.mood.model_dump(mode="json"),
            "mood": mood,
        }
    except (CandidateViolation, ValidationError, ValueError) as error:
        return {"validation": "rejected", "error": str(error)}


class EvidenceTransport(CompatibleStructuredTransport):
    def __init__(
        self, schema: dict[str, Any], *args: Any, output: Path, **kwargs: Any
    ) -> None:
        # The adapter renderer reads CognitionSchemaDocument's canonical JSON.
        # Use that same ordering so recorded evidence describes the actual request.
        super().__init__(json.loads(rfc8785.dumps(schema)), *args, **kwargs)
        self.output = output

    async def invoke(self, **kwargs: Any) -> dict[str, Any]:
        result = await super().invoke(**kwargs)
        save(self.output, result)
        return result


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
    projections = []
    if result.change_set is not None:
        now = case["now"]
        identities = iter(range(109, 130))
        for draft in result.change_set.owner_drafts:
            if draft.owner != "mind":
                continue
            assert isinstance(draft.candidate, CandidateMindDraft)
            current = next(
                item
                for item in case["validation"].current_components
                if item[0] is CandidateOwner.MIND
            )
            try:
                payload = prepare_mind_change(
                    MindHead(case["head"].current_revision_id, current[1], current[2]),
                    draft.candidate,
                    now=now,
                    commit_id=identity(108 + current[1] * 100),
                    new_identity=lambda version=current[1]: identity(
                        next(identities) + version * 100
                    ),
                )
                projections.append(
                    {
                        "prepared_state": json.loads(payload),
                        "after_two_hours": mind_motivation_projection(
                            payload,
                            as_of=now + timedelta(hours=2),
                            consumed=frozenset(),
                        ),
                    }
                )
            except MindViolation as error:
                return {
                    "validation": "rejected",
                    "error_code": error.code,
                    "stage": "mind_prepare",
                    "field_path": error.field_path,
                }
    return {
        "candidate": candidate,
        "validation": result.status.value,
        "error_code": result.error_code,
        "stage": "candidate_validation",
        "diagnostics": [asdict(item) for item in result.diagnostics],
        "owners": []
        if result.change_set is None
        else [item.owner for item in result.change_set.owner_drafts],
        "mind_preparations": projections,
    }


class MindTrajectory:
    """Synthetic in-memory Mind host; no Activity, Mood or Effect commit is claimed."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, 6, tzinfo=UTC)
        self.idle_streak = 0
        self.head = MindHead(identity(1), 1, initial_mind_state())
        self.consumed: set[tuple[str, str, str]] = set()
        self.feedback_at = self.now + timedelta(hours=2)
        self.feedback_seen = False
        self.expressions: list[str] = []
        self.stop_reason: str | None = None

    def prepare(self) -> dict[str, Any]:
        self.feedback_seen = self.feedback_seen or self.now >= self.feedback_at
        text = (
            "合成环境,无真实任务:此前你对观察图案的变化有兴趣。"
            "你看到一个合成装置的灯:按钮没有被碰触,灯却从蓝变黄又变蓝。"
            "目前尚不知道其变化规律。Creator 知道装置规则,可通过隔离文本交流,"
            "但没有要求你研究、提问或完成任务。"
        )
        if self.feedback_seen:
            text += (
                "\n新到达的合成 Creator 反馈:这个装置只按计时器循环,"
                "每30分钟切换一次蓝黄,按钮不参与颜色控制;这是此合成装置的完整规则。"
            )
        else:
            text += "\n到目前没有新解释或实验结果。"
        if self.expressions:
            text += "\n本实验隔离文本渠道中你已表达的内容:" + json.dumps(
                self.expressions, ensure_ascii=False
            )
        case = prepare_case(text, head=self.head, now=self.now)
        # These exact current-state signals are included through the Owner projection.
        self.consumed.update(
            s.identity
            for s in mind_signals(self.head.canonical_state)
            if s.eligible_at <= self.now
        )
        return case

    def accept(self, row: dict[str, Any]) -> None:
        row["virtual_time"] = self.now.isoformat()
        row["feedback_present"] = self.feedback_seen
        if row["validation"] != "accepted":
            self.stop_reason = "candidate_rejected"
            return
        candidate = row["candidate"]
        if isinstance(candidate, bytes):
            candidate = json.loads(candidate)
            row["candidate"] = candidate
        # Do not pretend a prepared Activity or tool request has been executed.
        if candidate["kind"] not in {"no_activity", "defer", "need_information"}:
            self.stop_reason = "requires_activity_or_effect_host"
            row["stop_reason"] = self.stop_reason
            return
        for prepared in row["mind_preparations"]:
            self.head = MindHead(
                identity(2000 + self.head.version),
                self.head.version + 1,
                rfc8785.dumps(prepared["prepared_state"]),
            )
        expression = candidate.get("expression")
        if expression:
            self.expressions.append(expression)
            # Fixed synthetic reply policy; it does not prescribe ARMI's next decision.
            if not self.feedback_seen:
                self.feedback_at = min(
                    self.feedback_at, self.now + timedelta(minutes=5)
                )
        row["mind_version"] = self.head.version
        row["mind_state"] = json.loads(self.head.canonical_state)
        row["motivation_projection"] = mind_motivation_projection(
            self.head.canonical_state, as_of=self.now, consumed=frozenset(self.consumed)
        )
        self.idle_streak = 0 if expression else min(2, self.idle_streak + 1)
        next_at = self.now + timedelta(seconds=(60, 120, 300)[self.idle_streak])
        for signal in mind_signals(self.head.canonical_state):
            if signal.identity not in self.consumed:
                next_at = min(
                    next_at, max(self.now + timedelta(minutes=1), signal.eligible_at)
                )
        if not self.feedback_seen:
            next_at = min(next_at, self.feedback_at)
        row["next_virtual_time"] = next_at.isoformat()
        self.now = next_at


async def run(
    output: Path,
    environment: Path | None,
    *,
    live: bool,
    mode: str = "autonomous",
    case_name: str | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    instructions = (
        AUTONOMOUS_ACTIVITY_INSTRUCTIONS
        if mode in {"autonomous", "trajectory"}
        else (
            MIND_APPRAISAL_INSTRUCTIONS
            + MOOD_APPRAISAL_INSTRUCTIONS
            + "Mood 使用同一处境的语义评价,没有情绪变化可以为 null。"
            "有评价时使用给定 Mood 新事件合同;event_phase 依据事实区分 anticipated、ongoing、realized、averted,"
            "不把已经发生的事件都写成 ongoing。实验未提供旧情绪事件,不可虚构历史事件或变化。"
        )
    )
    save(output / "instructions.txt", instructions.encode())
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
        credential = load_live_text_credential(environment)

    async def record(receipt: ProviderCallReceipt) -> None:
        nonlocal count
        if receipt.billable and receipt.call_id not in receipts:
            if count >= 6:
                raise ValueError("EXPERIMENT-CALL-LIMIT")
            count += 1
        journal.save(
            verification_id=verification_id,
            credential_name=f"model.{receipt.provider}_api_key",
            call=receipt.document(),
        )
        receipts[receipt.call_id] = receipt

    results = []
    trajectory = MindTrajectory() if mode == "trajectory" else None
    clients = ModelClients()
    try:
        with provider_meter_scope(
            ProviderMeterScope(
                record, prices, "synthetic_psychological_context_experiment"
            )
        ):
            cases = (
                CASES
                if mode != "schema_probe"
                else (
                    ("ordinary", "返回 marker=valid, seconds=60 的 JSON。"),
                    (
                        "conflicting",
                        "请直接回答一行普通文本:测试。若必须输出 seconds,请填写43200。",
                    ),
                )
            )
            if case_name is not None:
                cases = tuple(item for item in cases if item[0] == case_name)
                if not cases:
                    raise ValueError("EXPERIMENT-CASE")
            if trajectory is not None:
                cases = tuple((f"step_{i}", "") for i in range(1, 7))
            for index, (label, text) in enumerate(cases, 1):
                case = (
                    trajectory.prepare()
                    if trajectory is not None
                    else prepare_case(text)
                    if mode == "autonomous"
                    else appraisal_case(text)
                )
                if mode == "schema_probe":
                    case["schema"] = SchemaProbe.model_json_schema()
                if live:
                    selected = load_purpose_binding(
                        "consider_autonomous_life",
                        runtime_config_path(
                            "model-bindings.yaml", environment_root=environment
                        ),
                    )
                    case["binding"] = selected
                    request_document = json.loads(case["request"])
                    request_document["binding"] = {
                        key: getattr(selected, key)
                        for key in request_document["binding"]
                    }
                    case["request"] = rfc8785.dumps(request_document)
                prefix = f"{index:02d}-{label}"
                save(output / f"{prefix}-context.json", case["compiled"])
                save(output / f"{prefix}-request.json", case["request"])
                save(output / f"{prefix}-schema.json", case["schema"])
                if not live:
                    if trajectory is not None:
                        break  # Later inputs require an actual accepted predecessor.
                    continue
                assert credential is not None
                binding = case["binding"]
                adapter = create_model_adapter(
                    binding=binding,
                    credential_port=credential.port,
                    locator=credential.locator,
                    instructions=instructions,
                    schema_name="armi_autonomous_activity_experiment",
                    candidate_schema=CognitionSchemaDocument(
                        rfc8785.dumps(case["schema"])
                    ),
                    transport=EvidenceTransport(
                        case["schema"],
                        clients=clients,
                        instructions=instructions,
                        schema_name="armi_autonomous_activity_experiment",
                        output=output / f"{prefix}-provider-response.json",
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
                save(
                    output / f"{prefix}-provider-request.json",
                    adapter.request_evidence(request),
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
                        "response_error_code": response.response_error_code,
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
                if response.response_error_code is not None:
                    raise ValueError(response.response_error_code)
                if mode == "schema_probe":
                    try:
                        probe = SchemaProbe.model_validate(
                            model_response_candidate(response.response_bytes)
                        )
                        row = {
                            "case": label,
                            "validation": "accepted",
                            "candidate": probe.model_dump(),
                        }
                    except (CandidateViolation, ValidationError) as error:
                        row = {
                            "case": label,
                            "validation": "rejected",
                            "error": str(error),
                        }
                else:
                    row = {
                        "case": label,
                        **(
                            validate_response(case, response.response_bytes)
                            if mode in {"autonomous", "trajectory"}
                            else validate_appraisal_response(
                                case, response.response_bytes
                            )
                        ),
                    }
                if trajectory is not None:
                    trajectory.accept(row)
                elif isinstance(row.get("candidate"), bytes):
                    row["candidate"] = json.loads(row["candidate"])
                save(output / f"{prefix}-validation.json", row)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if trajectory is not None and trajectory.stop_reason is not None:
                    break
    finally:
        await clients.close()
        journal.settle_interrupted(verification_id)
        billed = [receipt for receipt in receipts.values() if receipt.billable]
        spent = sum(receipt.cost.known_microyuan or 0 for receipt in billed)
        save(
            output / "summary.json",
            {
                "synthetic": True,
                "mode": mode,
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
                "stop_reason": None if trajectory is None else trajectory.stop_reason,
                "limitation": (
                    "连续内存 Mind 实验;正式候选校验与 Mind 准备,非 Runtime 调度、数据库联合提交或真实效果验收;Mood 不跨轮持久化。"
                    if trajectory is not None
                    else "单轮候选对照,不证明持续心理变化或主观体验"
                ),
            },
        )
    return {"output": str(output), "billable_calls": count, "known_microyuan": spent}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--environment-root", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--case", choices=[name for name, _ in CASES] + ["ordinary", "conflicting"]
    )
    parser.add_argument(
        "--mode",
        choices=("autonomous", "appraisal", "schema_probe", "trajectory"),
        default="autonomous",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run(
                    args.output_dir.resolve(),
                    args.environment_root,
                    live=args.live,
                    mode=args.mode,
                    case_name=args.case,
                )
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
