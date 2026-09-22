"""Single-dispatch Jev appraisal transport; never a text-model fallback."""

from __future__ import annotations

from typing import Any, cast

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
)
from armi_local_control.configuration import ConfigurationViolation
from armi_mind.api import MindEvaluationTarget
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
    }
)


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
    ) -> EventAppraisalResult:
        result = await self._evaluate(
            assessment=assessment, context=context, targets=targets
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
            permitted = {
                (item["source"]["kind"], item["source"]["reference"])
                for item in items
                if "reference" in item.get("source", {})
                and item["item_kind"] not in _EXCLUDED_APPRAISAL_ITEMS
            } | {("event", str(assessment.event.source_ref))}
            basis = {reference for _, reference in permitted}
            if any(
                (target.object.source_kind, target.object.source_ref) not in permitted
                or not set(target.basis_refs) <= basis
                for target in targets
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
        goals = tuple(
            sorted(
                set(
                    item["source"]["reference"]
                    for item in items
                    if item["item_kind"] in {"current_concern", "current_motivation"}
                )
            )
        )
        joint = (
            None
            if targets is None
            else EventAppraisalRequest(
                assessment.event.event_key,
                str(assessment.assessment_id),
                assessment.event.occurred_at,
                situations,
                goals,
                targets,
            )
        )
        body = {
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
            "questions": appraisal_questions(situations, goals)
            if joint is None
            else joint.questions(),
        }
        try:
            async with (
                provider_call(
                    provider="typesafe", model=JEV_MODEL, service="generation"
                ) as call,
                httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=False, trust_env=False
                ) as client,
            ):
                response = await client.post(
                    "https://api.typesafe.ai/v1/systemone",
                    json=body,
                    headers={"Authorization": f"Bearer {key}"},
                )
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
                        goals=goals,
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
