"""Single-dispatch Jev appraisal transport; never a text-model fallback."""

from __future__ import annotations

from typing import Any, cast

import httpx
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    provider_call,
)
from armi_local_control.configuration import ConfigurationViolation
from armi_mood.api import (
    JEV_MODEL,
    EvaluatedAppraisal,
    MoodAssessment,
    MoodViolation,
    appraisal_questions,
    parse_appraisal_response,
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
                    if item["item_kind"]
                    not in {
                        "fixed_prompt",
                        "creator_prompt",
                        "subject_prompt",
                        "mood",
                        "active_affective_episode",
                    }
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
            "questions": appraisal_questions(situations, goals),
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
