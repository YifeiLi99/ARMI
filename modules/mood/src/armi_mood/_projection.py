"""VA and event emotions, with private event details in separate Context items."""

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import PsychologicalContextItem

from ._evaluation_contract import MoodView


def mood_snapshot_bytes(mood: MoodView) -> bytes:
    episodes: list[dict[str, Any]] = []
    emotions: list[dict[str, Any]] = []
    for episode in mood.state.episodes:
        decay = 2 ** (
            -(mood.as_of - episode.observed_at).total_seconds()
            / mood.state.parameters.fast_half_life_seconds
        )
        components = [
            {
                "kind": item.kind.value,
                "intensity": item.intensity * decay,
                "event_id": episode.event_id,
                "basis": list(item.basis),
            }
            for item in episode.response.emotions
            if item.intensity * decay > 0.001
        ]
        emotions.extend(components)
        if components:
            episodes.append(
                {
                    "episode_id": episode.situation_id,
                    "event_id": episode.event_id,
                    "gist": episode.summary,
                    "event_phase": episode.appraisal.phase,
                    "intensity": max(item["intensity"] for item in components),
                    "unknown": list(episode.response.unknown),
                }
            )
    return rfc8785.dumps(
        {
            "schema_kind": "armi.mood-snapshot",
            "as_of": mood.as_of.isoformat(),
            "current": mood.current.model_dump(),
            "active_emotions": emotions,
            "active_episodes": episodes,
            "quality": {
                "status": mood.evaluation_status,
                "assessment_id": None
                if mood.assessment_id is None
                else str(mood.assessment_id),
                "failure_code": mood.failure_code,
                "unknown": list(mood.unknown),
            },
        }
    )


def active_mood_episodes(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...] | bytes,
) -> tuple[tuple[UUID, str, int], ...]:
    payloads = (
        (component_payloads,)
        if isinstance(component_payloads, bytes)
        else tuple(
            payload for kind, _, _, payload in component_payloads if kind == "mood"
        )
    )
    if not payloads:
        return ()
    document = json.loads(payloads[-1])
    return tuple(
        (
            UUID(item["episode_id"]),
            rfc8785.dumps(
                {
                    "schema_kind": "armi.active-affective-episode",
                    **item,
                }
            ).decode(),
            round(item["intensity"] * 100),
        )
        for item in sorted(
            document["active_episodes"],
            key=lambda item: item["intensity"],
            reverse=True,
        )[:5]
    )


def active_mood_gists(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...],
) -> tuple[str, ...]:
    return tuple(
        json.loads(payload)["gist"][:80]
        for _, payload, intensity in active_mood_episodes(component_payloads)
        if intensity >= 20
    )[:2]


def mood_dialogue_text(mapping: dict[str, object]) -> str:
    current = cast(dict[str, Any], mapping["current"])
    return f"当前感受(愉快度={current['valence']}, 激活度={current['arousal']})"


def mood_context_items(
    payload: bytes, *, revision_id: UUID, version: int
) -> tuple[PsychologicalContextItem, ...]:
    public_affect = json.loads(payload)
    # Audience profiles can exclude episode details without leaking them in mood.
    public_affect.pop("active_episodes")
    # Private goal identities and event explanations follow their own Context items.
    public_affect["active_emotions"] = [
        {"kind": item["kind"], "intensity": item["intensity"]}
        for item in public_affect["active_emotions"]
    ]
    public_affect["quality"]["unknown"] = [
        item
        for item in public_affect["quality"]["unknown"]
        if not item.startswith("goal:")
    ]
    return (
        PsychologicalContextItem(
            "mood",
            "mood",
            revision_id,
            version,
            rfc8785.dumps(public_affect).decode(),
            False,
            90,
        ),
        *(
            PsychologicalContextItem(
                "active_affective_episode",
                "mood_episode",
                episode_id,
                version,
                content,
                False,
                max(70, min(99, intensity)),
            )
            for episode_id, content, intensity in active_mood_episodes(payload)
        ),
    )
