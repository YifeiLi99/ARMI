"""Single Jev Choice request for the frozen autonomous check Context."""

import json
from typing import Any, cast

import httpx
from armi_cognition.api import autonomy_check_questions
from armi_context.api import autonomy_wake_state
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    ModelBinding,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
)
from armi_local_control.configuration import ConfigurationViolation
from armi_mood.api import JEV_MODEL

from .jev_transport import jev_request


class JevAutonomyCheck:
    def __init__(
        self,
        *,
        credentials: CredentialPort,
        locator: CredentialLocator | None,
        timeout_seconds: int,
        decision_check: bool = False,
    ) -> None:
        self._credentials = credentials
        self._locator = locator
        self._purpose = "cognition.decision" if decision_check else "autonomy.check"
        self.binding = ModelBinding(
            provider="typesafe",
            api_base="https://api.typesafe.ai/v1",
            model_id=JEV_MODEL,
            version_policy="fixed_provider_model",
            response_model_identity_required=True,
            profile="bounded_decision" if decision_check else "autonomy_check",
            response_contract_kind="armi.bounded-decision"
            if decision_check
            else "armi.autonomy-check",
            credential_identity="mood.jev_api_key",
            input_token_limit=32000 if decision_check else 1000,
            output_token_limit=128,
            timeout_seconds=timeout_seconds,
            attempt_cost_limit_microyuan=1_000_000,
        )

    def request_evidence(self, context: bytes) -> bytes:
        state = autonomy_wake_state(context)
        request = json.dumps(
            {
                "model": JEV_MODEL,
                "state": state,
                "questions": autonomy_check_questions(
                    cast(list[str], state["available_directions"])
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        # Bound prompt growth before a billable call; bytes are not provider tokens.
        if len(request) > 4096:
            raise ModelViolation("MODEL-JEV-CHECK-SIZE")
        return request

    async def invoke(self, request: bytes) -> ModelInvocationResult:
        if self._locator is None:
            raise ModelViolation("MODEL-CREDENTIAL-JEV")
        try:
            with self._credentials.resolve(
                self._locator, CredentialPurpose(self._purpose)
            ) as handle:
                key = handle.consume(lambda value: bytes(value).decode("utf-8"))
        except ConfigurationViolation:
            raise ModelViolation("MODEL-CREDENTIAL-JEV") from None
        try:
            wire = httpx.Request(
                "POST",
                self.binding.api_base + "/systemone",
                content=request,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            async with jev_request(
                wire, timeout_seconds=self.binding.timeout_seconds
            ) as (response, call):
                response.raise_for_status()
                document = response.json()
                if not isinstance(document, dict):
                    raise ModelViolation("MODEL-JEV-CHECK-CONTRACT")
                raw = cast(dict[str, Any], document)
                request_id = response.headers.get("x-request-id")
                await call.capture(
                    usage=raw.get("usage"),
                    response_model=raw.get("model"),
                    provider_request_id=request_id,
                )
                if raw.get("model") != JEV_MODEL:
                    raise ModelViolation("MODEL-JEV-CHECK-CONTRACT")
                usage = raw["usage"]
                return ModelInvocationResult(
                    status=ModelResultStatus.SUCCEEDED,
                    provider_request_id=request_id,
                    provider_model_id=JEV_MODEL,
                    response_bytes=response.content,
                    usage=ModelUsage(usage["input_tokens"], usage["output_tokens"], 0),
                )
        except httpx.HTTPStatusError as error:
            raise ModelViolation(
                "MODEL-AUTH-JEV"
                if error.response.status_code in {401, 403}
                else "MODEL-JEV-HTTP-FAILED"
            ) from None
        except httpx.ConnectTimeout:
            raise ModelViolation("MODEL-JEV-CONNECT-TIMEOUT") from None
        except httpx.ConnectError:
            raise ModelViolation("MODEL-JEV-CONNECT-FAILED") from None
        except httpx.TimeoutException:
            raise ModelViolation(
                "MODEL-OUTCOME-UNKNOWN", outcome_unknown=True
            ) from None
        except httpx.RequestError:
            raise ModelViolation(
                "MODEL-OUTCOME-UNKNOWN", outcome_unknown=True
            ) from None
        except ValueError, KeyError, TypeError:
            raise ModelViolation("MODEL-JEV-CHECK-CONTRACT") from None
        finally:
            key = ""
