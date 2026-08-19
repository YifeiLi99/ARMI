"""Low-latency Ark Responses adapter with tools and thinking disabled."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from armi_live_voice.api import LiveVoiceViolation, VoiceContext


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
                stream: Any = await self._client.responses.create(
                    model=self._model,
                    instructions="实时语音预热,只输出OK。",
                    input="开始",
                    max_output_tokens=8,
                    tools=[],
                    store=False,
                    stream=True,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                async for _ in stream:
                    pass
        except Exception as error:
            raise LiveVoiceViolation(
                "VOICE-LLM-PREPARE-FAILED", "fast model warmup failed"
            ) from error

    async def generate(
        self, context: VoiceContext, transcript: str
    ) -> AsyncIterator[str]:
        if not transcript.strip():
            raise LiveVoiceViolation("VOICE-EMPTY-TRANSCRIPT", "transcript is empty")
        instruction = (
            context.prompt
            + "\n\n实时语音。首行从SPEAK/WAIT/SILENT三选一,只输出所选结果。"
            "SPEAK第二行一句回答(最多60字);WAIT第二行垫话(最多12字);"
            "SILENT无第二行。"
            "无工具、解释或Markdown。"
        )
        try:
            stream: Any = await self._client.responses.create(
                model=self._model,
                instructions=instruction,
                input=transcript,
                max_output_tokens=96,
                tools=[],
                store=False,
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield str(delta)
        except Exception as error:
            raise LiveVoiceViolation("VOICE-LLM-FAILED", "fast model failed") from error
