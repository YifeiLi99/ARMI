"""Privacy-preserving one-to-one Mood family to display mapping."""

from __future__ import annotations

from armi_mood.api import MoodView

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
    DisplayExpression.OFFLINE: "#AAB4C4",
}


def map_mood_snapshot(snapshot: MoodView) -> DisplayState:
    candidates = [
        (
            emotion.kind.value,
            emotion.intensity
            * 2
            ** (
                -(snapshot.as_of - episode.observed_at).total_seconds()
                / snapshot.state.parameters.fast_half_life_seconds
            ),
        )
        for episode in snapshot.state.episodes
        for emotion in episode.response.emotions
    ]
    strongest = max(candidates, key=lambda item: item[1], default=("neutral", 0))
    # The physical face repertoire renders disappointment with its sad face.
    name = "sadness" if strongest[0] == "disappointment" else strongest[0]
    expression = (
        DisplayExpression[name.upper()]
        if strongest[1] > 0.001
        else DisplayExpression.NEUTRAL
    )
    raw_energy = (snapshot.current.arousal + 1) * 50
    energy = int((raw_energy + 5) // 10) * 10
    return DisplayState(
        snapshot.version,
        expression,
        _COLORS[expression],
        "#000000",
        max(0, min(100, energy)),
    )


__all__ = ("map_mood_snapshot",)
