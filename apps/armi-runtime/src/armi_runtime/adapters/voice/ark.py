"""Low-latency Ark Responses adapter with tools and thinking disabled."""

from __future__ import annotations

import asyncio
from typing import Any

from armi_live_voice.api import LiveVoiceViolation


class ArkResponsesFastModel:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "doubao-seed-character-260628",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    ) -> None:
        if not api_key:
            raise LiveVoiceViolation("VOICE-LLM-CREDENTIAL", "Ark API key is empty")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._prepare_lock = asyncio.Lock()

    async def prepare(self) -> None:
        """Warm the selected model when an explicit voice session starts."""
        try:
            async with self._prepare_lock:
                response: Any = await self._client.responses.create(
                    model=self._model,
                    instructions="严格按 JSON Schema 输出语音兼容检查结果。",
                    input="开始",
                    max_output_tokens=32,
                    tools=[],
                    store=False,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "armi_voice_compatibility",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    extra_body={"thinking": {"type": "disabled"}},
                )
                if response.output_text != '{"ok":true}':
                    raise LiveVoiceViolation(
                        "VOICE-LLM-STRICT-JSON", "fast model lacks strict JSON support"
                    )
        except Exception as error:
            raise LiveVoiceViolation(
                "VOICE-LLM-PREPARE-FAILED", "fast model warmup failed"
            ) from error
