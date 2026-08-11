"""Doubao Speech large-model ASR for downloaded external audio."""

from __future__ import annotations

import asyncio
import base64
import json
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
_QUEUED = "20000001"
_PROCESSING = "20000002"
_SUCCEEDED = "20000000"


@dataclass(frozen=True, slots=True)
class DoubaoSpeechRecognitionBinding:
    submit_url: str
    query_url: str
    resource_id: str
    model_name: str
    model_version: str
    timeout_seconds: int
    poll_interval_seconds: float

    @property
    def model_identity(self) -> str:
        return f"{self.model_name}-{self.model_version}"


@dataclass(frozen=True, slots=True)
class _Credentials:
    app_id: str
    access_token: str


class _CredentialFormatError(ValueError):
    pass


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
            credentials = _decode_credentials(secret)
            request_id = str(uuid4())
            headers = {
                "X-Api-App-Key": credentials.app_id,
                "X-Api-Access-Key": credentials.access_token,
                "X-Api-Resource-Id": self._binding.resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Sequence": "-1",
            }
            async with asyncio.timeout(self._binding.timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self._binding.timeout_seconds,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    submitted = await client.post(
                        self._binding.submit_url,
                        headers=headers,
                        json={
                            "user": {"uid": credentials.app_id},
                            "audio": {
                                "data": base64.b64encode(request.content).decode(
                                    "ascii"
                                ),
                                "format": _audio_format(request),
                            },
                            "request": {
                                "model_name": self._binding.model_name,
                                "model_version": self._binding.model_version,
                                "enable_itn": True,
                                "enable_punc": True,
                                "enable_ddc": True,
                                "show_utterances": True,
                            },
                        },
                    )
                    submitted.raise_for_status()
                    rejection = self._provider_rejection(submitted)
                    if rejection is not None:
                        return rejection
                    log_id = submitted.headers.get("X-Tt-Logid")
                    query_headers = dict(headers)
                    if log_id:
                        query_headers["X-Tt-Logid"] = log_id
                    while True:
                        response = await client.post(
                            self._binding.query_url,
                            headers=query_headers,
                            json={},
                        )
                        response.raise_for_status()
                        status_code = response.headers.get("X-Api-Status-Code")
                        if status_code == _SUCCEEDED:
                            return self._decode_response(
                                response, fallback_log_id=log_id
                            )
                        if status_code not in {_QUEUED, _PROCESSING}:
                            return self._provider_failure(response)
                        await asyncio.sleep(self._binding.poll_interval_seconds)
        except TimeoutError, httpx.TimeoutException, httpx.TransportError:
            return _failure(
                ExternalContentRecognitionStatus.UNKNOWN,
                self._binding.model_identity,
                "EXTERNAL-MESSAGE-RECOGNITION-UNKNOWN",
            )
        except httpx.HTTPStatusError as error:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                self._binding.model_identity,
                f"EXTERNAL-MESSAGE-RECOGNITION-HTTP-{error.response.status_code}",
            )
        except _CredentialFormatError:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                self._binding.model_identity,
                "EXTERNAL-MESSAGE-RECOGNITION-CREDENTIAL",
            )
        except UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError:
            return _failure(
                ExternalContentRecognitionStatus.FAILED,
                self._binding.model_identity,
                "EXTERNAL-MESSAGE-RECOGNITION-RESPONSE",
            )
        finally:
            for index in range(len(secret)):
                secret[index] = 0

    def _provider_rejection(
        self, response: httpx.Response
    ) -> ExternalContentRecognitionResult | None:
        if response.headers.get("X-Api-Status-Code") == _SUCCEEDED:
            return None
        return self._provider_failure(response)

    def _provider_failure(
        self, response: httpx.Response
    ) -> ExternalContentRecognitionResult:
        status_code = response.headers.get("X-Api-Status-Code")
        code = status_code if status_code and status_code.isdecimal() else "INVALID"
        return ExternalContentRecognitionResult(
            ExternalContentRecognitionStatus.FAILED,
            None,
            _PROVIDER,
            self._binding.model_identity,
            None,
            response.headers.get("X-Tt-Logid"),
            None,
            None,
            None,
            f"EXTERNAL-MESSAGE-RECOGNITION-ASR-{code}",
        )

    def _decode_response(
        self, response: httpx.Response, *, fallback_log_id: str | None
    ) -> ExternalContentRecognitionResult:
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
            self._binding.model_identity,
            None,
            response.headers.get("X-Tt-Logid") or fallback_log_id,
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


def _decode_credentials(secret: bytearray) -> _Credentials:
    try:
        document = json.loads(secret.decode("utf-8", errors="strict"))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise _CredentialFormatError("speech credentials are invalid") from None
    if type(document) is not dict or set(document) != {"app_id", "access_token"}:
        raise _CredentialFormatError("speech credentials are invalid")
    app_id = document["app_id"]
    access_token = document["access_token"]
    if (
        type(app_id) is not str
        or not app_id.strip()
        or type(access_token) is not str
        or not access_token.strip()
    ):
        raise _CredentialFormatError("speech credentials are invalid")
    return _Credentials(app_id, access_token)


def _audio_format(request: ExternalContentRecognitionRequest) -> str:
    formats = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/ogg": "ogg",
        "audio/opus": "ogg",
    }
    try:
        return formats[request.media_type.lower()]
    except KeyError:
        raise ExternalMessageViolation(
            "EXTERNAL-MESSAGE-RECOGNITION-MEDIA-TYPE"
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
