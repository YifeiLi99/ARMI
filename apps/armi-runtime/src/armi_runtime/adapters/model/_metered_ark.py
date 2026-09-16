"""Save Responses API metering before any consumer interprets its output."""

from typing import Any, cast

from armi_kernel.application import provider_call
from openai import AsyncOpenAI
from openai.types.responses import Response


async def metered_ark_response(
    client: AsyncOpenAI,
    *,
    model: str,
    service: str = "generation",
    **parameters: Any,
) -> Response:
    async with provider_call(
        provider="volcengine_ark", model=model, service=service
    ) as call:
        response = cast(
            Response, await client.responses.create(model=model, **parameters)
        )
        raw_usage = response.model_dump(mode="json").get("usage")
        await call.capture(
            usage=cast(dict[str, object], raw_usage)
            if isinstance(raw_usage, dict)
            else None,
            provider_request_id=getattr(response, "_request_id", None) or response.id,
            response_model=response.model,
        )
        return response
