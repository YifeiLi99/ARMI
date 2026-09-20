"""Bounded provider checks for explicit setup requests; no Runtime or life writes."""

# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import json
import sys
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from armi_cognition.bootstrap import load_active_model_binding, load_voice_model_binding
from armi_kernel.application import (
    ModelRequest,
    ModelViolation,
    ProviderCallReceipt,
    ProviderMeterScope,
    load_price_catalog,
    provider_meter_scope,
)
from armi_kernel.contracts import Digest
from armi_local_control import ProviderCheckReceipts
from armi_local_control.configuration import load_effective_config
from openai import AsyncOpenAI

from armi_runtime.adapters.model._metered_ark import metered_ark_response
from armi_runtime.adapters.model.compatible import CompatibleStructuredTransport
from armi_runtime.adapters.voice.volc import (
    VolcStreamingAsr,
    VolcStreamingTts,
    decode_volc_credentials,
)

from .config_assets import runtime_config_path

_PHRASE = "你好，这是语音连接测试。"


def _failure(error: Exception) -> dict[str, Any]:
    # Provider messages can contain request details. Return only codes and safe guidance.
    chain: BaseException | None = error
    status = None
    code = None
    connection_failed = False
    while chain is not None:
        status = status or getattr(chain, "status_code", None)
        connection_failed = connection_failed or isinstance(chain, ConnectionError)
        response = getattr(chain, "response", None)
        status = status or getattr(response, "status_code", None)
        candidate = getattr(chain, "code", None)
        if isinstance(candidate, str) and candidate.startswith(
            ("VOICE-", "MODEL-", "CFG-")
        ):
            code = candidate
        chain = chain.__cause__
    message = "连接或协议验证失败，请检查网络、服务开通状态及资源配置。"
    if status in (401, 403):
        message = "鉴权或权限失败，请检查 Key、项目权限和服务是否开通。"
    elif status == 429:
        message = "服务限流或额度不足，请检查控制台。"
    elif isinstance(error, TimeoutError):
        message = "验证超时，请检查网络后重试。"
    elif connection_failed:
        message = "网络连接失败，请检查服务地址和网络可达性。"
    elif code in {"MODEL-CONTEXT", "MODEL-REQUEST", "MODEL-BINDING-MANIFEST"}:
        message = "本地验证请求或模型配置不符合合同，尚未完成供应商验证；请检查 ARMI 验证实现。"
    elif code == "MODEL-PROVIDER-RESPONSE":
        message = "供应商已返回响应，但模型身份或严格结构化输出校验未通过。"
    return {
        "status": "failed",
        "error_code": f"HTTP-{status}"
        if isinstance(status, int)
        else code or "PROVIDER-VERIFY-FAILED",
        "message": message,
    }


async def _model_check(key: str, binding: Any) -> dict[str, Any]:
    if binding.provider in {"qwen", "deepseek"}:
        transport = CompatibleStructuredTransport(
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            instructions='连接测试，请输出 {"candidate":{"ok":true}}。',
            schema_name="armi_connection_check",
        )
        try:
            request_bytes = json.dumps(
                {
                    "schema_version": "armi.model-request.v1",
                    "compiled_context": {
                        "purpose": "consider_creator_input",
                        "layers": [
                            {
                                "items": [
                                    {
                                        "item_kind": "current_evidence",
                                        "content": "连接测试，请输出指定 JSON。",
                                    }
                                ]
                            }
                        ],
                    },
                    "included_context_refs": [{"ref": "ctx:1"}],
                }
            ).encode()
            response = await transport.invoke(
                api_key=memoryview(key.encode()),
                binding=binding,
                request=ModelRequest(
                    request_bytes, Digest.from_bytes(request_bytes), 1, 64
                ),
            )
            try:
                output = json.loads(response["output_text"])
            except json.JSONDecodeError:
                raise ModelViolation("MODEL-PROVIDER-RESPONSE") from None
            if (
                response["raw"].get("status") != "completed"
                or not response["raw"].get("output")
                or any(
                    item.get("type") != "message" for item in response["raw"]["output"]
                )
                or response["model_id"] != binding.model_id
                or output != {"candidate": {"ok": True}}
            ):
                raise ModelViolation("MODEL-PROVIDER-RESPONSE")
            return {"status": "passed", "model": binding.model_id}
        finally:
            await transport.close()
    async with AsyncOpenAI(
        api_key=key,
        base_url=binding.api_base,
        timeout=25,
        max_retries=0,
        http_client=httpx.AsyncClient(trust_env=False),
    ) as client:
        response = await metered_ark_response(
            client,
            model=binding.model_id,
            input='连接测试，请输出 {"ok":true}。',
            store=False,
            max_output_tokens=32,
            tools=[],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "armi_connection_check",
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
        if json.loads(response.output_text) != {"ok": True}:
            raise ValueError("provider output mismatch")
        return {"status": "passed", "model": binding.model_id}


async def verify(
    name: str, key: str, root: Path, verification_id: str
) -> dict[str, Any]:
    if UUID(verification_id).version != 7:
        raise ValueError("USAGE-ADMIN-RECEIPT")
    journal = ProviderCheckReceipts(root)
    prices = load_price_catalog(
        runtime_config_path("provider-pricing.yaml", environment_root=root)
    )

    async def save(receipt: ProviderCallReceipt) -> None:
        await asyncio.to_thread(
            journal.save,
            verification_id=verification_id,
            credential_name=name,
            call=receipt.document(),
        )

    with provider_meter_scope(
        ProviderMeterScope(save, prices, "credential_verification")
    ):
        result = await _verify(name, key, root)
    return {**result, "verification_id": verification_id}


async def _verify(name: str, key: str, root: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if name in {"model.ark_api_key", "model.qwen_api_key", "model.deepseek_api_key"}:
        path = runtime_config_path("model-bindings.yaml", environment_root=root)
        provider = {
            "model.ark_api_key": "volcengine_ark",
            "model.qwen_api_key": "qwen",
            "model.deepseek_api_key": "deepseek",
        }[name]
        loaders = (
            (("voice_model", load_voice_model_binding),)
            if provider == "volcengine_ark"
            else (("model", load_active_model_binding),)
        )
        for label, loader in loaders:
            try:
                binding = loader(path)
                if binding.provider != provider:
                    # Credential checks are independent of the active chat provider.
                    # Use this provider's documented probe model; never switch runtime configuration.
                    binding = replace(
                        binding,
                        provider=provider,
                        model_id="qwen3.8-flash"
                        if provider == "qwen"
                        else "deepseek-flash",
                        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1"
                        if provider == "qwen"
                        else "https://api.deepseek.com",
                        credential_identity=f"armi.model.{provider}-api-key.v1",
                    )
                async with asyncio.timeout(30):
                    checks[label] = await _model_check(key, binding)
            except Exception as error:
                checks[label] = _failure(error)
    elif name == "speech.volc_credentials":
        config = load_effective_config(
            defaults_path=runtime_config_path("runtime.yaml"),
            environment_path=root / "environment.yaml",
        ).config.voice
        credentials = decode_volc_credentials(key.encode())
        tts = VolcStreamingTts(
            credentials,
            resource_id=config.tts_resource_id,
            voice_type=config.tts_voice_type,
        )
        audio = bytearray()

        async def fragments():
            yield _PHRASE

        try:
            async with asyncio.timeout(30):
                async for block in tts.synthesize(fragments()):
                    audio.extend(block)
                    if len(audio) > 32000 * 15:
                        raise ValueError("probe audio too long")
                if not audio:
                    raise ValueError("empty synthesis")
            checks["tts"] = {"status": "passed", "audio_bytes": len(audio)}
        except Exception as error:
            checks["tts"] = _failure(error)
        finally:
            await tts.close()
        if checks["tts"]["status"] == "passed":

            async def frames():
                for offset in range(0, len(audio), 6400):
                    yield bytes(audio[offset : offset + 6400])
                    await asyncio.sleep(0.2)

            try:
                async with asyncio.timeout(30):
                    asr = VolcStreamingAsr(
                        credentials, resource_id=config.asr_resource_id
                    )
                    text = ""
                    async for event in asr.recognize(frames()):
                        if event.text:
                            text = event.text

                    def normalize(value: str) -> str:
                        return "".join(
                            c
                            for c in value
                            if not unicodedata.category(c).startswith(("P", "Z"))
                        )

                    if normalize(text) != normalize(_PHRASE):
                        raise ValueError("recognition mismatch")
                checks["asr"] = {"status": "passed"}
            except Exception as error:
                checks["asr"] = _failure(error)
        else:
            checks["asr"] = {
                "status": "not_tested",
                "message": "TTS 未生成测试音频，ASR 尚未验证。",
            }
    else:
        raise ValueError("unsupported credential")
    return {
        "status": "passed"
        if all(item["status"] == "passed" for item in checks.values())
        else "failed",
        "checks": checks,
    }


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError("input size")
        request = json.loads(raw)
        result = asyncio.run(
            verify(
                request["name"],
                request["key"],
                Path(request["root"]),
                request["verification_id"],
            )
        )
    except Exception as error:
        result = _failure(error)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
