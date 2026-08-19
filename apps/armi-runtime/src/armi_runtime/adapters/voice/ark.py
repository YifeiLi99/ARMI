"""Low-latency Ark Responses adapter with tools and thinking disabled."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from armi_live_voice.api import LiveVoiceViolation, VoiceContext


class ArkResponsesFastModel:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "doubao-seed-2-0-mini-260428",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    ) -> None:
        if not api_key:
            raise LiveVoiceViolation("VOICE-LLM-CREDENTIAL", "Ark API key is empty")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def generate(
        self, context: VoiceContext, transcript: str
    ) -> AsyncIterator[str]:
        if not transcript.strip():
            raise LiveVoiceViolation("VOICE-EMPTY-TRANSCRIPT", "transcript is empty")
        instruction = (
            context.prompt
            + "\n\n你正在进行本机实时语音快答。只允许使用以下首行协议之一\uff1a\n"
            "SPEAK\n<一至两句、最多160字>\n"
            "WAIT\n<最多24字的自然垫话>\n"
            "SILENT\n\n"
            "不要使用工具\uff0c不要输出解释或 Markdown。"
        )
        try:
            stream: Any = await self._client.responses.create(
                model=self._model,
                instructions=instruction,
                input=transcript,
                max_output_tokens=192,
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
