"""Volcengine Ark visual, video, and document recognition."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import rfc8785
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    ExternalContentRecognitionPort,
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionResult,
    ExternalContentRecognitionStatus,
    ExternalMessagePartKind,
    ExternalMessageViolation,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from .doubao_speech import DoubaoSpeechRecognitionBinding

_PURPOSE = CredentialPurpose("model.request")


@dataclass(frozen=True, slots=True)
class ArkExternalRecognitionBinding:
    api_base: str
    visual_document_model_id: str
    video_model_id: str
    output_token_limit: int
    timeout_seconds: int

    def model_for(self, kind: ExternalMessagePartKind) -> str:
        return (
            self.video_model_id
            if kind is ExternalMessagePartKind.VIDEO
            else self.visual_document_model_id
        )


@dataclass(frozen=True, slots=True)
class ExternalRecognitionBindings:
    ark: ArkExternalRecognitionBinding
    speech: DoubaoSpeechRecognitionBinding

    def target_for(self, kind: ExternalMessagePartKind) -> tuple[str, str]:
        if kind is ExternalMessagePartKind.AUDIO:
            return "volcengine_doubao_speech", self.speech.model_identity
        return "volcengine_ark", self.ark.model_for(kind)


class VolcengineArkExternalContentRecognizer(ExternalContentRecognitionPort):
    __slots__ = ("_binding", "_credential_port", "_locator")

    def __init__(
        self,
        *,
        credential_port: CredentialPort,
        locator: CredentialLocator,
        binding: ArkExternalRecognitionBinding,
    ) -> None:
        self._credential_port = credential_port
        self._locator = locator
        self._binding = binding

    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult:
        if request.kind is ExternalMessagePartKind.AUDIO:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RECOGNITION-KIND")
        model_id = self._binding.model_for(request.kind)
        secret = self._copy_secret()
        client: AsyncOpenAI | None = None
        try:
            client = AsyncOpenAI(
                api_key=secret.decode("utf-8", errors="strict"),
                base_url=self._binding.api_base,
                max_retries=0,
                timeout=self._binding.timeout_seconds,
                http_client=httpx.AsyncClient(trust_env=False),
            )
            response = await client.responses.create(
                model=model_id,
                input=cast(Any, [_input_message(request)]),
                store=False,
                max_output_tokens=self._binding.output_token_limit,
                tools=[],
                extra_body={"thinking": {"type": "disabled"}},
            )
            output_text = response.output_text
            if type(output_text) is not str or not output_text.strip():
                return _failure(
                    ExternalContentRecognitionStatus.FAILED,
                    model_id,
                    "EXTERNAL-MESSAGE-RECOGNITION-RESPONSE",
                )
            usage = response.usage
            raw = rfc8785.dumps(cast(Any, response.model_dump(mode="json"))) + b"\n"
            return ExternalContentRecognitionResult(
                ExternalContentRecognitionStatus.SUCCEEDED,
                output_text,
                "volcengine_ark",
                model_id,
                response.model,
                response.id,
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
                raw,
                None,
            )
        except APITimeoutError, APIConnectionError:
            return _failure(
                ExternalContentRecognitionStatus.UNKNOWN,
                model_id,
                "EXTERNAL-MESSAGE-RECOGNITION-UNKNOWN",
            )
        except APIStatusError as error:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                model_id,
                f"EXTERNAL-MESSAGE-RECOGNITION-HTTP-{error.status_code}",
            )
        except UnicodeDecodeError, ValueError, TypeError:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                model_id,
                "EXTERNAL-MESSAGE-RECOGNITION-RESPONSE",
            )
        finally:
            for index in range(len(secret)):
                secret[index] = 0
            if client is not None:
                await client.close()

    def _copy_secret(self) -> bytearray:
        try:
            with self._credential_port.resolve(self._locator, _PURPOSE) as handle:
                return handle.consume(lambda value: bytearray(value))
        except Exception:
            raise ExternalMessageViolation(
                "EXTERNAL-MESSAGE-RECOGNITION-CREDENTIAL"
            ) from None


def load_external_recognition_binding(path: Path) -> ExternalRecognitionBindings:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))[
            "external_content_recognition"
        ]
        ark = ArkExternalRecognitionBinding(
            api_base=value["api_base"],
            visual_document_model_id=value["visual_document_model_id"],
            video_model_id=value["video_model_id"],
            output_token_limit=value["output_token_limit"],
            timeout_seconds=value["timeout_seconds"],
        )
        speech = DoubaoSpeechRecognitionBinding(
            submit_url=value["speech_submit_url"],
            query_url=value["speech_query_url"],
            resource_id=value["speech_resource_id"],
            model_name=value["speech_model_name"],
            model_version=value["speech_model_version"],
            timeout_seconds=value["speech_timeout_seconds"],
            poll_interval_seconds=value["speech_poll_interval_seconds"],
        )
    except OSError, KeyError, TypeError, json.JSONDecodeError:
        raise ValueError("external recognition binding is invalid") from None
    if (
        ark.api_base != "https://ark.cn-beijing.volces.com/api/v3"
        or not ark.visual_document_model_id
        or not ark.video_model_id
        or not 1 <= ark.output_token_limit <= 4096
        or not 1 <= ark.timeout_seconds <= 300
        or speech.submit_url
        != "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
        or speech.query_url
        != "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
        or speech.resource_id != "volc.bigasr.auc"
        or speech.model_name != "bigmodel"
        or speech.model_version != "400"
        or not 1 <= speech.timeout_seconds <= 300
        or not 0.1 <= speech.poll_interval_seconds <= 10
    ):
        raise ValueError("external recognition binding is invalid")
    return ExternalRecognitionBindings(ark=ark, speech=speech)


def _input_message(request: ExternalContentRecognitionRequest) -> dict[str, Any]:
    encoded = base64.b64encode(request.content).decode("ascii")
    instructions = {
        ExternalMessagePartKind.IMAGE: "描述图片中实际可见的内容和文字,不确定之处必须明确标出。",
        ExternalMessagePartKind.VIDEO: "按时间顺序概括画面、动作、可见文字和声音,不确定之处必须明确标出。",
        ExternalMessagePartKind.FILE: "概括 PDF 的结构和主要内容,不确定或无法读取之处必须明确标出。",
    }[request.kind]
    if request.kind is ExternalMessagePartKind.IMAGE:
        media = {
            "type": "input_image",
            "image_url": f"data:{request.media_type};base64,{encoded}",
        }
    elif request.kind is ExternalMessagePartKind.VIDEO:
        media = {
            "type": "input_video",
            "video_url": f"data:{request.media_type};base64,{encoded}",
        }
    else:
        media = {
            "type": "input_file",
            "filename": request.file_name,
            "file_data": f"data:{request.media_type};base64,{encoded}",
        }
    return {
        "role": "user",
        "content": [{"type": "input_text", "text": instructions}, media],
    }


def _failure(
    status: ExternalContentRecognitionStatus, model_id: str, code: str
) -> ExternalContentRecognitionResult:
    return ExternalContentRecognitionResult(
        status,
        None,
        "volcengine_ark",
        model_id,
        None,
        None,
        None,
        None,
        None,
        code,
    )


__all__ = (
    "ArkExternalRecognitionBinding",
    "ExternalRecognitionBindings",
    "VolcengineArkExternalContentRecognizer",
    "load_external_recognition_binding",
)
