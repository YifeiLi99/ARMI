"""Single-dispatch Jev appraisal transport; never a text-model fallback."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

import httpx
from armi_cognition.api import (
    EventAppraisalRequest,
    EventAppraisalResult,
    parse_event_appraisal,
)
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    provider_call,
    record_diagnostic,
)
from armi_local_control.configuration import ConfigurationViolation
from armi_mind.api import GroundedObject, MindEvaluationTarget
from armi_mood.api import (
    JEV_MODEL,
    EvaluatedAppraisal,
    MoodAssessment,
    MoodViolation,
    appraisal_questions,
    parse_appraisal_response,
)

_EXCLUDED_APPRAISAL_ITEMS = frozenset(
    {
        "fixed_prompt",
        "creator_prompt",
        "subject_prompt",
        "mood",
        "active_affective_episode",
        "runtime_identity",
        "current_purpose",
        "capability_catalog",
        "current_evidence",
    }
)


def _share_evaluation_rules(body: dict[str, Any]) -> None:
    """Keep identical evaluation rules once in Jev's shared state.

    All questions see this state (TypeSafe primitives documentation).
    """
    questions = [
        question
        for name, question in body["questions"].items()
        if name.startswith("mind_")
    ]
    mood = [
        question
        for name, question in body["questions"].items()
        if not name.startswith("mind_")
    ]
    shared = {}
    for name, entries, field in (
        ("mind_scope", [q["instructions"]["评价对象"] for q in questions], "范围"),
        ("mood_scope", [q["instructions"] for q in mood], "评价对象"),
        (
            "mood_boundary",
            [q["instructions"] for q in mood if "边界" in q["instructions"]],
            "边界",
        ),
    ):
        if not entries:
            continue
        rules = entries[0][field]
        if any(entry[field] != rules for entry in entries):
            raise ValueError("shared evaluation rules differ")
        shared[name] = rules
        for entry in entries:
            entry[field] = (
                f"遵守共享 state 中 `evaluation_rules.{name}` 的全部评价边界。"
            )
    body["state"]["evaluation_rules"] = shared


class JevAppraiser:
    def __init__(
        self,
        *,
        credentials: CredentialPort,
        locator: CredentialLocator | None,
        timeout_seconds: int,
    ) -> None:
        self._credentials = credentials
        self._locator = locator
        self._timeout = timeout_seconds

    async def evaluate(
        self, *, assessment: MoodAssessment, context: dict[str, Any]
    ) -> EvaluatedAppraisal:
        result = await self._evaluate(
            assessment=assessment, context=context, targets=None
        )
        if not isinstance(result, EvaluatedAppraisal):
            raise ValueError("unexpected Jev result contract")
        return result

    async def evaluate_event(
        self,
        *,
        assessment: MoodAssessment,
        context: dict[str, Any],
        targets: tuple[MindEvaluationTarget, ...],
        capture: Callable[[Literal["request", "response"], str], Awaitable[None]]
        | None = None,
    ) -> EventAppraisalResult:
        result = await self._evaluate(
            assessment=assessment, context=context, targets=targets, capture=capture
        )
        if not isinstance(result, EventAppraisalResult):
            raise ValueError("unexpected Jev result contract")
        return result

    async def _evaluate(
        self,
        *,
        assessment: MoodAssessment,
        context: dict[str, Any],
        targets: tuple[MindEvaluationTarget, ...] | None,
        capture: Callable[[Literal["request", "response"], str], Awaitable[None]]
        | None = None,
    ) -> EvaluatedAppraisal | EventAppraisalResult:
        if self._locator is None:
            raise MoodViolation("MOOD-JEV-CREDENTIAL-MISSING")
        try:
            with self._credentials.resolve(
                self._locator, CredentialPurpose("mood.appraisal")
            ) as handle:
                key = handle.consume(lambda value: bytes(value).decode("utf-8").strip())
        except ConfigurationViolation, UnicodeError:
            raise MoodViolation("MOOD-JEV-CREDENTIAL-UNAVAILABLE") from None
        if (
            not key
            or not key.isascii()
            or any(character.isspace() for character in key)
        ):
            raise MoodViolation("MOOD-JEV-CREDENTIAL-INVALID")
        # Only Context-authorized episodes may be exposed to this event's audience.
        items = [item for layer in context["layers"] for item in layer["items"]]
        if targets is not None:
            event_ref = str(assessment.event.source_ref)
            if targets != (
                MindEvaluationTarget(GroundedObject("event", event_ref), (event_ref,)),
            ):
                raise MoodViolation("MOOD-JEV-MIND-SOURCE-FORBIDDEN")
        allowed = {
            item["source"]["reference"]
            for item in items
            if item["item_kind"] == "active_affective_episode"
        }
        previous = tuple(
            episode
            for episode in assessment.state.episodes
            if episode.situation_id in allowed
        )[-253:]
        situations = tuple(episode.situation_id for episode in previous)
        joint = (
            None
            if targets is None
            else EventAppraisalRequest(
                assessment.event.event_key,
                str(assessment.assessment_id),
                assessment.event.occurred_at,
                situations,
                targets,
            )
        )
        body: dict[str, Any] = {
            "model": JEV_MODEL,
            "state": {
                "event": {
                    "id": str(assessment.assessment_id),
                    "source_ref": str(assessment.event.source_ref),
                    "occurred_at": assessment.event.occurred_at.isoformat(),
                    "content": assessment.event.summary,
                },
                "context": [
                    item
                    for item in items
                    if item["item_kind"] not in _EXCLUDED_APPRAISAL_ITEMS
                ],
                "previous_situations": [
                    {
                        "id": episode.situation_id,
                        "content": episode.summary,
                        "appraisal": episode.appraisal.model_dump(mode="json"),
                    }
                    for episode in previous
                ],
            },
            "questions": appraisal_questions(situations)
            if joint is None
            else joint.questions(),
        }
        _share_evaluation_rules(body)
        record_diagnostic(
            "mood.jev.request.prepared",
            component="appraisal",
            request_bytes=len(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            question_count=len(body["questions"]),
            context_item_count=len(body["state"]["context"]),
            previous_situation_count=len(previous),
        )
        try:
            async with (
                provider_call(
                    provider="typesafe", model=JEV_MODEL, service="generation"
                ) as call,
                httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=False, trust_env=False
                ) as client,
            ):
                request = client.build_request(
                    "POST",
                    "https://api.typesafe.ai/v1/systemone",
                    json=body,
                    headers={"Authorization": f"Bearer {key}"},
                )
                # Retain actual wire bodies, never credentials or HTTP headers.
                if capture is not None:
                    await capture("request", request.content.decode("utf-8"))
                response = await client.send(request)
                if capture is not None:
                    await capture("response", response.text)
                response.raise_for_status()
                document = response.json()
                if not isinstance(document, dict):
                    raise MoodViolation("MOOD-JEV-CONTRACT")
                raw = cast(dict[str, Any], document)
                await call.capture(
                    usage=raw.get("usage"),
                    response_model=raw.get("model"),
                    provider_request_id=response.headers.get("x-request-id"),
                )
                try:
                    if joint is not None:
                        return parse_event_appraisal(raw, request=joint)
                    return parse_appraisal_response(
                        raw,
                        event_id=str(assessment.assessment_id),
                        situations=situations,
                    )
                except ValueError, TypeError, KeyError:
                    raise MoodViolation("MOOD-JEV-CONTRACT") from None
        except httpx.HTTPStatusError:
            raise MoodViolation("MOOD-JEV-HTTP-FAILED") from None
        except httpx.TimeoutException:
            raise MoodViolation("MOOD-JEV-OUTCOME-UNKNOWN") from None
        except httpx.RequestError, ValueError:
            raise MoodViolation("MOOD-JEV-RESPONSE-FAILED") from None
        finally:
            key = ""
