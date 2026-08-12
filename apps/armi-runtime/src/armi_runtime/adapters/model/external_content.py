"""Volcengine Ark visual, video, and document recognition."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import rfc8785
from armi_interaction.api import (
    ExternalContentRecognitionPort,
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionResult,
    ExternalContentRecognitionStatus,
    ExternalMessagePartKind,
    ExternalMessageViolation,
    ExternalVisualRole,
)
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
)
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from .doubao_speech import DoubaoSpeechRecognitionBinding

_PURPOSE = CredentialPurpose("model.request")


@dataclass(frozen=True, slots=True)
class ArkExternalRecognitionBinding:
    api_base: str
    image_model_id: str
    document_model_id: str
    video_model_id: str
    output_token_limit: int
    image_output_token_limit: int
    sticker_output_token_limit: int
    timeout_seconds: int

    def model_for(self, kind: ExternalMessagePartKind) -> str:
        if kind is ExternalMessagePartKind.IMAGE:
            return self.image_model_id
        if kind is ExternalMessagePartKind.VIDEO:
            return self.video_model_id
        return self.document_model_id

    def output_limit_for(self, request: ExternalContentRecognitionRequest) -> int:
        if request.kind is not ExternalMessagePartKind.IMAGE:
            return self.output_token_limit
        if request.visual_role in {
            ExternalVisualRole.STICKER,
            ExternalVisualRole.STICKER_CANDIDATE,
        }:
            return self.sticker_output_token_limit
        return self.image_output_token_limit


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
                max_output_tokens=self._binding.output_limit_for(request),
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
        value = load_yaml_file(path)["external_content_recognition"]
        ark = ArkExternalRecognitionBinding(
            api_base=value["api_base"],
            image_model_id=value["image_model_id"],
            document_model_id=value["document_model_id"],
            video_model_id=value["video_model_id"],
            output_token_limit=value["output_token_limit"],
            image_output_token_limit=value["image_output_token_limit"],
            sticker_output_token_limit=value["sticker_output_token_limit"],
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
    except OSError, KeyError, TypeError, ValueError:
        raise ValueError("external recognition binding is invalid") from None
    if (
        ark.api_base != "https://ark.cn-beijing.volces.com/api/v3"
        or not ark.image_model_id
        or not ark.document_model_id
        or not ark.video_model_id
        or not 1 <= ark.output_token_limit <= 4096
        or not 1 <= ark.image_output_token_limit <= 4096
        or not 1 <= ark.sticker_output_token_limit <= 4096
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
    instructions = {
        ExternalMessagePartKind.VIDEO: "按时间顺序概括画面、动作、可见文字和声音,不确定之处必须明确标出。",
        ExternalMessagePartKind.FILE: "概括 PDF 的结构和主要内容,不确定或无法读取之处必须明确标出。",
    }.get(request.kind)
    if request.kind is ExternalMessagePartKind.IMAGE:
        instructions = _image_instructions(request)
        media = [
            {
                "type": "input_image",
                "image_url": (
                    f"data:{item.media_type};base64,"
                    f"{base64.b64encode(item.content).decode('ascii')}"
                ),
            }
            for item in request.visual_inputs
        ]
    elif request.kind is ExternalMessagePartKind.VIDEO:
        encoded = base64.b64encode(request.content).decode("ascii")
        media = [
            {
                "type": "input_video",
                "video_url": f"data:{request.media_type};base64,{encoded}",
            }
        ]
    else:
        encoded = base64.b64encode(request.content).decode("ascii")
        media = [
            {
                "type": "input_file",
                "filename": request.file_name,
                "file_data": f"data:{request.media_type};base64,{encoded}",
            }
        ]
    assert instructions is not None
    return {
        "role": "user",
        "content": [{"type": "input_text", "text": instructions}, *media],
    }


def _image_instructions(request: ExternalContentRecognitionRequest) -> str:
    source = f"平台来源类别为 {request.source_kind}。"
    summary = (
        f"QQ 提供的摘要是“{request.source_summary}”,它只是平台元数据,需与画面核对。"
        if request.source_summary
        else "QQ 没有提供有效摘要。"
    )
    animation = (
        f"输入按时间顺序包含 {len(request.visual_inputs)} 个代表帧。"
        if len(request.visual_inputs) > 1
        else "输入是一张静态图。"
    )
    if request.visual_role in {
        ExternalVisualRole.STICKER,
        ExternalVisualRole.STICKER_CANDIDATE,
    }:
        task = "简洁说明表情中的角色、动作、情绪、可见文字和在聊天中的表达作用。"
    elif request.visual_role is ExternalVisualRole.PLATFORM_SPECIAL:
        task = "说明实际可见内容、文字以及这张平台特殊图片在聊天中的表达作用。"
    elif request.visual_role is ExternalVisualRole.ORDINARY:
        task = "客观描述图片中实际可见的内容和文字。"
    else:
        task = "先判断它更像照片、截图、梗图、表情包、文档图或其他图片,再简洁描述内容和文字。"
    return f"{source}{summary}{animation}{task}不确定之处必须明确标出。"


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
