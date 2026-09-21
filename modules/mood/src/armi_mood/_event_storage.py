"""Mood storage decoding shared by authorized read adapters."""

from typing import Any, cast

from armi_mood.api import AppraisalEventPhase, AppraisalTransition, MoodViolation

from ._domain import (
    StoredAffectiveEvent,
    StoredCoreAffect,
    StoredEmotionComponent,
    parse_component,
    parse_vad,
)

EVENT_QUERY = """SELECT e.mood_episode_id,e.transition,e.event_phase,e.gist,
                          e.derived_components,e.occurred_at,r.subject_commit_id,e.mood_appraisal_event_id,
                          e.derived_vad,e.affect_intensity,e.affect_half_life_seconds
                   FROM armi.mood_appraisal_events e
                   JOIN armi.mood_revisions r ON r.mood_revision_id=e.mood_revision_id
                   WHERE (%s::uuid IS NULL OR e.subject_id=%s) AND occurred_at <= %s
                     AND occurred_at >= %s - (%s * interval '1 day')
                   ORDER BY occurred_at,mood_appraisal_event_id"""


def parse_events(appraisal_rows: Any) -> tuple[StoredAffectiveEvent, ...]:
    events: list[StoredAffectiveEvent] = []
    try:
        for (
            episode_id,
            transition,
            phase,
            gist,
            raw_components,
            occurred_at,
            source_commit_id,
            event_id,
            vad,
            intensity,
            half_life,
        ) in appraisal_rows:
            events.append(
                StoredAffectiveEvent(
                    occurred_at,
                    stored_components(raw_components),
                    episode_id,
                    AppraisalTransition(transition),
                    AppraisalEventPhase(phase),
                    str(gist),
                    source_commit_id,
                    event_id,
                    core=StoredCoreAffect(
                        parse_vad(vad, step=None), intensity, half_life
                    ),
                )
            )
    except MoodViolation, TypeError, ValueError:
        raise MoodViolation("MOOD-EVENT-STORAGE") from None
    events.sort(key=lambda item: item.occurred_at)
    return tuple(events)


def stored_components(
    raw_components: object,
) -> tuple[StoredEmotionComponent, ...]:
    components: list[StoredEmotionComponent] = []
    for raw in cast(list[object], raw_components):
        item = cast(dict[str, object], raw)
        half_life = item.get("half_life_seconds")
        if type(half_life) is not int:
            raise ValueError
        semantic = {
            key: value for key, value in item.items() if key != "half_life_seconds"
        }
        components.append(StoredEmotionComponent(parse_component(semantic), half_life))
    return tuple(components)
