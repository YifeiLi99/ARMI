from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar
from uuid import uuid7

import httpx
import pytest
from armi_interaction.api import ExternalMessagePartKind
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    CredentialPurpose,
    SecretHandle,
)
from armi_kernel.contracts import TraceId
from armi_perception.api import (
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionStatus,
)
from armi_runtime.adapters.model import doubao_speech
from armi_runtime.adapters.model.doubao_speech import (
    DoubaoSpeechRecognitionBinding,
    DoubaoSpeechRecognizer,
)

_T = TypeVar("_T")


class _Handle:
    def __init__(self) -> None:
        self._value = bytearray(b'{"app_id":"app","access_token":"token"}')
        self.closed = False

    def consume(self, operation: Callable[[memoryview], _T]) -> _T:
        return operation(memoryview(self._value).toreadonly())

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _Handle:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


class _Credentials(CredentialPort):
    def resolve(
        self, locator: CredentialLocator, purpose: CredentialPurpose
    ) -> SecretHandle:
        assert locator.identity() == "env:DOUBAO_SPEECH"
        assert purpose.value == "speech.recognition"
        return _Handle()


def _recognizer(handler: httpx.AsyncBaseTransport) -> DoubaoSpeechRecognizer:
    return DoubaoSpeechRecognizer(
        credential_port=_Credentials(),
        locator=CredentialLocator("env", "DOUBAO_SPEECH"),
        binding=DoubaoSpeechRecognitionBinding(
            "https://speech.invalid/submit",
            "https://speech.invalid/query",
            "resource",
            "model",
            "v1",
            2,
            0.0,
        ),
        transport=handler,
    )


def _request() -> ExternalContentRecognitionRequest:
    return ExternalContentRecognitionRequest(
        ExternalMessagePartKind.AUDIO,
        b"audio",
        "voice.mp3",
        "audio/mpeg",
        TraceId(uuid7().hex),
    )


@pytest.mark.asyncio
async def test_accepted_task_retries_query_503_then_preserves_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_sleep = asyncio.sleep

    async def immediate_sleep(_seconds: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(doubao_speech.asyncio, "sleep", immediate_sleep)
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/submit":
            return httpx.Response(
                200,
                headers={"X-Api-Status-Code": "20000000", "X-Tt-Logid": "task-1"},
            )
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={"result": {"text": "已识别"}},
        )

    result = await _recognizer(httpx.MockTransport(handler)).recognize(_request())

    assert result.status is ExternalContentRecognitionStatus.SUCCEEDED
    assert result.text == "已识别"
    assert result.provider_request_id == "task-1"
    assert calls == 3


@pytest.mark.asyncio
async def test_submit_503_is_unknown_but_explicit_provider_terminal_is_failed() -> None:
    async def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    unknown = await _recognizer(httpx.MockTransport(unavailable)).recognize(_request())
    assert unknown.status is ExternalContentRecognitionStatus.UNKNOWN

    async def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"X-Api-Status-Code": "20000100"})

    failed = await _recognizer(httpx.MockTransport(rejected)).recognize(_request())
    assert failed.status is ExternalContentRecognitionStatus.FAILED
