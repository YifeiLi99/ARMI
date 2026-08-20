"""Live-voice composition with scoped credential resolution."""

from __future__ import annotations

from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_interaction.api import CreatorIdentityContext, CreatorInteractionPort
from armi_kernel.application import CredentialPurpose
from armi_live_voice.api import (
    AudioFormat,
    LiveVoiceBinding,
    LiveVoiceRuntimePort,
    LiveVoiceViolation,
    VoiceProviderBinding,
    VoiceProviderService,
)
from armi_live_voice.bootstrap import compose_live_voice, compose_live_voice_journal
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_subject_state.api import SubjectStateReadPort

from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.voice.ark import ArkResponsesFastModel
from armi_runtime.adapters.voice.volc import (
    VolcStreamingAsr,
    VolcStreamingTts,
    decode_volc_credentials,
)
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio
from armi_runtime.application.live_voice import (
    RuntimeLiveVoiceContext,
    RuntimeLiveVoiceInteraction,
)

from .environment import PreparedEnvironment

_MODEL_PURPOSE = CredentialPurpose("voice.fast-model")
_SPEECH_PURPOSE = CredentialPurpose("voice.streaming-speech")


def compose_runtime_live_voice(
    prepared: PreparedEnvironment,
    *,
    factory: PostgreSQLUnitOfWorkFactory,
    subject_id: UUID,
    creator: CreatorIdentityContext,
    interaction: CreatorInteractionPort,
    subject_state: SubjectStateReadPort,
    mood: MoodReadPort,
    prompt: PromptReadPort,
    relationship: RelationshipReadPort,
    catalog: ArtifactCatalogPort,
) -> LiveVoiceRuntimePort | None:
    config = prepared.effective.config
    voice = config.voice
    if not voice.enabled:
        return None
    input_device = voice.input_device
    output_device = voice.output_device
    if input_device is None or output_device is None:
        raise LiveVoiceViolation("VOICE-DEVICE-CONFIG", "voice device is not configured")
    model_locator = config.secret_locators.get("model.ark_api_key")
    speech_locator = config.secret_locators.get("speech.volc_credentials")
    if model_locator is None or speech_locator is None:
        raise LiveVoiceViolation(
            "VOICE-CREDENTIAL-UNAVAILABLE", "voice credential is not configured"
        )
    try:
        with prepared.credential_port.resolve(model_locator, _MODEL_PURPOSE) as handle:
            model_key = handle.consume(
                lambda value: value.tobytes().decode("utf-8", errors="strict").strip()
            )
        with prepared.credential_port.resolve(speech_locator, _SPEECH_PURPOSE) as handle:
            speech_secret = handle.consume(lambda value: bytearray(value))
        try:
            speech_credentials = decode_volc_credentials(speech_secret)
        finally:
            for index in range(len(speech_secret)):
                speech_secret[index] = 0
    except LiveVoiceViolation:
        raise
    except Exception:
        raise LiveVoiceViolation(
            "VOICE-CREDENTIAL-UNAVAILABLE", "voice credential is unavailable"
        ) from None
    if not model_key:
        raise LiveVoiceViolation("VOICE-LLM-CREDENTIAL", "Ark API key is empty")

    binding = LiveVoiceBinding(
        input_host_api=input_device.host_api,
        input_device_name=input_device.name,
        output_host_api=output_device.host_api,
        output_device_name=output_device.name,
        asr=VoiceProviderBinding(
            VoiceProviderService.ASR,
            "volcengine",
            voice.asr_resource_id,
        ),
        llm=VoiceProviderBinding(
            VoiceProviderService.LLM,
            "volcengine_ark",
            voice.llm_model,
            voice.llm_model,
        ),
        tts=VoiceProviderBinding(
            VoiceProviderService.TTS,
            "volcengine",
            voice.tts_resource_id,
            voice.tts_voice_type,
        ),
    )
    audio = WasapiRawAudio(
        input_host_api=input_device.host_api,
        input_name=input_device.name,
        output_host_api=output_device.host_api,
        output_name=output_device.name,
        audio_format=AudioFormat(
            sample_rate_hz=voice.sample_rate_hz,
            channels=voice.channels,
            sample_width_bytes=voice.sample_width_bytes,
            frame_duration_ms=voice.frame_duration_ms,
        ),
        queue_max_frames=voice.queue_max_frames,
    )
    journal = compose_live_voice_journal(
        factory=factory,
        subject_id=subject_id,
        creator_party_id=creator.party_id,
        scene_id=creator.scene_id,
        binding=binding,
    )
    bridge = RuntimeLiveVoiceInteraction(
        acceptance=interaction,
        successor=interaction,
        scene_key=creator.default_scene_key,
    )
    return compose_live_voice(
        audio=audio,
        asr=VolcStreamingAsr(
            speech_credentials,
            resource_id=voice.asr_resource_id,
            endpoint_silence_ms=voice.endpoint_silence_ms,
        ),
        model=ArkResponsesFastModel(model_key, model=voice.llm_model),
        tts=VolcStreamingTts(
            speech_credentials,
            resource_id=voice.tts_resource_id,
            voice_type=voice.tts_voice_type,
        ),
        context=RuntimeLiveVoiceContext(
            factory=factory,
            subject_id=subject_id,
            subject_state=subject_state,
            mood=mood,
            prompt=prompt,
            relationship=relationship,
            catalog=catalog,
            storage=ContentAddressedArtifactStore(
                prepared.data_root / "artifacts",
                max_object_bytes=config.artifacts.max_object_bytes,
            ),
        ),
        inputs=bridge,
        expression=journal,
        successors=bridge,
        journal=journal,
        binding=binding,
    )


__all__ = ("compose_runtime_live_voice",)
