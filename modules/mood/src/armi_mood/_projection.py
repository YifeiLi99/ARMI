"""Mood-owned cognitive projection, salience and presentation policy."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .api import MoodSnapshot
from uuid import UUID

import rfc8785
from armi_kernel.application import PsychologicalContextItem


def active_mood_episodes(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...] | bytes,
) -> tuple[tuple[UUID, str, int], ...]:
    payloads = (
        (component_payloads,)
        if isinstance(component_payloads, bytes)
        else tuple(
            payload
            for kind, _source_id, _version, payload in component_payloads
            if kind == "mood"
        )
    )
    if not payloads:
        return ()
    try:
        decoded = json.loads(payloads[-1])
        if not isinstance(decoded, dict):
            raise ValueError("invalid mood projection")
        document = cast(dict[str, object], decoded)
        if document.get("schema_kind") != ("armi.mood-snapshot"):
            raise ValueError("invalid mood projection")
        raw_episodes = document.get("active_episodes")
        if not isinstance(raw_episodes, list):
            raise ValueError("invalid mood projection")
        result: list[tuple[UUID, str, int]] = []
        for decoded_episode in cast(list[object], raw_episodes)[:5]:
            if not isinstance(decoded_episode, dict):
                raise ValueError("invalid mood projection")
            raw = cast(dict[str, object], decoded_episode)
            episode_id = UUID(str(raw["episode_id"]))
            gist = str(raw["gist"])
            phase = str(raw["event_phase"])
            intensity = raw["intensity"]
            if (
                episode_id.version != 7
                or not gist.strip()
                or len(gist) > 64
                or phase not in {"anticipated", "ongoing", "realized", "averted"}
                or type(intensity) is not int
                or not 0 <= intensity <= 100
            ):
                raise ValueError("invalid mood projection")
            result.append(
                (
                    episode_id,
                    rfc8785.dumps(
                        {
                            "schema_kind": "armi.active-affective-episode",
                            "gist": gist,
                            "event_phase": phase,
                            "intensity": intensity,
                        }
                    ).decode("utf-8"),
                    intensity,
                )
            )
        return tuple(result)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        from .api import MoodViolation

        raise MoodViolation("MOOD-SNAPSHOT-STORAGE") from error


def active_mood_gists(
    component_payloads: tuple[tuple[str, UUID, int, bytes], ...],
) -> tuple[str, ...]:
    remaining = 160
    result: list[str] = []
    for _episode_id, payload, intensity in active_mood_episodes(component_payloads):
        if intensity < 20 or len(result) == 2 or remaining <= 0:
            continue
        gist = str(cast(dict[str, object], json.loads(payload))["gist"])
        piece = gist[:remaining]
        if piece:
            result.append(piece)
            remaining -= len(piece)
    return tuple(result)


def mood_dialogue_text(mapping: dict[str, object]) -> str:
    current = cast(dict[str, object], mapping.get("current", {}))
    emotions = cast(list[dict[str, object]], mapping.get("active_emotions", []))
    tendencies = cast(list[dict[str, object]], mapping.get("action_tendencies", []))
    parts = [
        "当前核心感受"
        f"(愉悦={current.get('valence', 0)},"
        f"唤醒={current.get('arousal', 0)},"
        f"掌控={current.get('dominance', 0)})"
    ]
    if emotions:
        parts.append(
            "活动情绪:"
            + ";".join(
                f"{item.get('nuance', item.get('family'))}({item.get('intensity')})"
                for item in emotions[:3]
            )
        )
    if tendencies:
        parts.append(
            "行动倾向建议:"
            + ";".join(
                f"{item.get('tendency')}({item.get('intensity')})"
                for item in tendencies[:2]
            )
        )
    return ";".join(parts)


def mood_snapshot_bytes(mood: MoodSnapshot) -> bytes:
    return rfc8785.dumps(
        {
            "schema_kind": "armi.mood-snapshot",
            "as_of": mood.as_of.isoformat(),
            "home_base": {
                "valence": mood.home_base.valence,
                "arousal": mood.home_base.arousal,
                "dominance": mood.home_base.dominance,
            },
            "current": {
                "valence": mood.current.valence,
                "arousal": mood.current.arousal,
                "dominance": mood.current.dominance,
            },
            "active_emotions": [
                {
                    "family": item.family.value,
                    "nuance": item.nuance,
                    "intensity": item.intensity,
                }
                for item in mood.active_emotions
            ],
            "active_episodes": [
                {
                    "episode_id": str(item.episode_id),
                    "gist": item.gist,
                    "event_phase": item.phase.value,
                    "intensity": item.intensity,
                }
                for item in mood.active_episodes
            ],
            "action_tendencies": [
                {
                    "tendency": item.tendency.value,
                    "intensity": item.intensity,
                }
                for item in mood.action_tendencies
            ],
        }
    )


def mood_context_items(
    payload: bytes,
    *,
    revision_id: UUID,
    version: int,
) -> tuple[PsychologicalContextItem, ...]:
    return (
        PsychologicalContextItem(
            "mood", "mood", revision_id, version, payload.decode("utf-8"), False, 90
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
