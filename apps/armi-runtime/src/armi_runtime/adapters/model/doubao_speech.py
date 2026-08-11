"""Doubao Speech large-model ASR for downloaded external audio."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from uuid import uuid4

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

_PURPOSE = CredentialPurpose("speech.recognition")
_PROVIDER = "volcengine_doubao_speech"


@dataclass(frozen=True, slots=True)
class DoubaoSpeechRecognitionBinding:
    api_url: str
    resource_id: str
    model_id: str
    timeout_seconds: int


class DoubaoSpeechRecognizer(ExternalContentRecognitionPort):
    __slots__ = ("_binding", "_credential_port", "_locator", "_transport")

    def __init__(
        self,
        *,
        credential_port: CredentialPort,
        locator: CredentialLocator,
        binding: DoubaoSpeechRecognitionBinding,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credential_port = credential_port
        self._locator = locator
        self._binding = binding
        self._transport = transport

    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult:
        if request.kind is not ExternalMessagePartKind.AUDIO:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RECOGNITION-KIND")
        secret = self._copy_secret()
        try:
            api_key = secret.decode("utf-8", errors="strict")
            request_id = str(uuid4())
            async with httpx.AsyncClient(
                timeout=self._binding.timeout_seconds,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._binding.api_url,
                    headers={
                        "X-Api-Key": api_key,
                        "X-Api-Resource-Id": self._binding.resource_id,
                        "X-Api-Request-Id": request_id,
                        "X-Api-Sequence": "-1",
                    },
                    json={
                        "user": {"uid": api_key},
                        "audio": {
                            "data": base64.b64encode(request.content).decode("ascii")
                        },
                        "request": {"model_name": self._binding.model_id},
                    },
                )
            response.raise_for_status()
            return self._decode_response(response)
        except httpx.TimeoutException, httpx.TransportError:
            return _failure(
                ExternalContentRecognitionStatus.UNKNOWN,
                self._binding.model_id,
                "EXTERNAL-MESSAGE-RECOGNITION-UNKNOWN",
            )
        except httpx.HTTPStatusError as error:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                self._binding.model_id,
                f"EXTERNAL-MESSAGE-RECOGNITION-HTTP-{error.response.status_code}",
            )
        except UnicodeDecodeError, ValueError, TypeError:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                self._binding.model_id,
                "EXTERNAL-MESSAGE-RECOGNITION-RESPONSE",
            )
        finally:
            for index in range(len(secret)):
                secret[index] = 0

    def _decode_response(
        self, response: httpx.Response
    ) -> ExternalContentRecognitionResult:
        status_code = response.headers.get("X-Api-Status-Code")
        provider_request_id = response.headers.get("X-Tt-Logid")
        if status_code != "20000000":
            code = status_code if status_code and status_code.isdecimal() else "INVALID"
            return ExternalContentRecognitionResult(
                ExternalContentRecognitionStatus.FAILED,
                None,
                _PROVIDER,
                self._binding.model_id,
                None,
                provider_request_id,
                None,
                None,
                None,
                f"EXTERNAL-MESSAGE-RECOGNITION-ASR-{code}",
            )
        document = response.json()
        if type(document) is not dict:
            raise ValueError("ASR response must be an object")
        result = document.get("result")
        if type(result) is not dict:
            raise ValueError("ASR result must be an object")
        text = result.get("text")
        if type(text) is not str or not text.strip():
            raise ValueError("ASR result text is missing")
        raw = rfc8785.dumps(document) + b"\n"
        return ExternalContentRecognitionResult(
            ExternalContentRecognitionStatus.SUCCEEDED,
            text,
            _PROVIDER,
            self._binding.model_id,
            None,
            provider_request_id,
            None,
            None,
            raw,
            None,
        )

    def _copy_secret(self) -> bytearray:
        try:
            with self._credential_port.resolve(self._locator, _PURPOSE) as handle:
                return handle.consume(lambda value: bytearray(value))
        except Exception:
            raise ExternalMessageViolation(
                "EXTERNAL-MESSAGE-RECOGNITION-CREDENTIAL"
            ) from None


def _failure(
    status: ExternalContentRecognitionStatus, model_id: str, code: str
) -> ExternalContentRecognitionResult:
    return ExternalContentRecognitionResult(
        status,
        None,
        _PROVIDER,
        model_id,
        None,
        None,
        None,
        None,
        None,
        code,
    )


__all__ = (
    "DoubaoSpeechRecognitionBinding",
    "DoubaoSpeechRecognizer",
)
