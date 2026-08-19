"""Privacy-preserving one-to-one Mood family to display mapping."""

from __future__ import annotations

from armi_mood.api import MoodSnapshot

from .api import DisplayExpression, DisplayState

_COLORS = {
    DisplayExpression.JOY: "#FFD166",
    DisplayExpression.CONTENTMENT: "#6BCB77",
    DisplayExpression.INTEREST: "#4CC9F0",
    DisplayExpression.HOPE: "#72DDF7",
    DisplayExpression.RELIEF: "#52B69A",
    DisplayExpression.AFFECTION: "#FF7AA2",
    DisplayExpression.GRATITUDE: "#F4A261",
    DisplayExpression.PRIDE: "#C77DFF",
    DisplayExpression.SURPRISE: "#FF9F1C",
    DisplayExpression.SADNESS: "#4E79A7",
    DisplayExpression.FEAR: "#6C63A8",
    DisplayExpression.ANXIETY: "#8F77B5",
    DisplayExpression.ANGER: "#E15759",
    DisplayExpression.FRUSTRATION: "#F05D5E",
    DisplayExpression.DISGUST: "#7A9E3A",
    DisplayExpression.SHAME: "#B565A7",
    DisplayExpression.GUILT: "#D7799F",
    DisplayExpression.JEALOUSY: "#83A14A",
    DisplayExpression.BOREDOM: "#7D8597",
    DisplayExpression.CONFUSION: "#5DADE2",
    DisplayExpression.NEUTRAL: "#667085",
    DisplayExpression.OFFLINE: "#3A3F47",
}


def map_mood_snapshot(snapshot: MoodSnapshot) -> DisplayState:
    expression = (
        DisplayExpression[snapshot.active_emotions[0].family.name]
        if snapshot.active_emotions
        else DisplayExpression.NEUTRAL
    )
    raw_energy = (snapshot.current_vad.arousal + 100) / 2
    energy = int((raw_energy + 5) // 10) * 10
    return DisplayState(
        snapshot.version,
        expression,
        _COLORS[expression],
        "#000000",
        max(0, min(100, energy)),
    )


__all__ = ("map_mood_snapshot",)
