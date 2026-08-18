"""Privacy-preserving Mood snapshot to face mapping."""

from __future__ import annotations

from armi_mood.api import EmotionFamily, MoodSnapshot

from .api import DisplayExpression, DisplayState

_COLORS = {
    DisplayExpression.HAPPY: "#F6C85F",
    DisplayExpression.EXCITED: "#F28E2B",
    DisplayExpression.CALM: "#4EAAA5",
    DisplayExpression.SAD: "#4E79A7",
    DisplayExpression.ANXIOUS: "#8F77B5",
    DisplayExpression.ANGRY: "#E15759",
    DisplayExpression.DISGUSTED: "#7A9E3A",
    DisplayExpression.EMBARRASSED: "#D7799F",
    DisplayExpression.NEUTRAL: "#667085",
    DisplayExpression.OFFLINE: "#3A3F47",
}


def _from_family(snapshot: MoodSnapshot) -> DisplayExpression | None:
    if not snapshot.active_emotions:
        return None
    family = snapshot.active_emotions[0].family
    if family in {
        EmotionFamily.JOY,
        EmotionFamily.AFFECTION,
        EmotionFamily.GRATITUDE,
        EmotionFamily.PRIDE,
    }:
        if family is EmotionFamily.JOY and snapshot.current_vad.arousal >= 60:
            return DisplayExpression.EXCITED
        return DisplayExpression.HAPPY
    if family in {EmotionFamily.INTEREST, EmotionFamily.HOPE}:
        return DisplayExpression.EXCITED
    if family in {EmotionFamily.CONTENTMENT, EmotionFamily.RELIEF}:
        return DisplayExpression.CALM
    if family in {EmotionFamily.SADNESS, EmotionFamily.BOREDOM}:
        return DisplayExpression.SAD
    if family in {EmotionFamily.FEAR, EmotionFamily.ANXIETY}:
        return DisplayExpression.ANXIOUS
    if family in {EmotionFamily.ANGER, EmotionFamily.FRUSTRATION}:
        return DisplayExpression.ANGRY
    if family is EmotionFamily.DISGUST:
        return DisplayExpression.DISGUSTED
    if family in {EmotionFamily.SHAME, EmotionFamily.GUILT}:
        return DisplayExpression.EMBARRASSED
    if family is EmotionFamily.SURPRISE:
        return (
            DisplayExpression.EXCITED
            if snapshot.current_vad.valence >= 0
            else DisplayExpression.ANXIOUS
        )
    if family is EmotionFamily.JEALOUSY:
        return (
            DisplayExpression.ANGRY
            if snapshot.current_vad.dominance >= 0
            else DisplayExpression.ANXIOUS
        )
    return None


def _from_vad(snapshot: MoodSnapshot) -> DisplayExpression:
    vad = snapshot.current_vad
    if abs(vad.valence) < 20 and abs(vad.arousal) < 25:
        return DisplayExpression.NEUTRAL
    if vad.valence >= 25:
        if vad.arousal >= 45:
            return DisplayExpression.EXCITED
        if vad.arousal <= -20:
            return DisplayExpression.CALM
        return DisplayExpression.HAPPY
    if vad.valence <= -25:
        if vad.arousal >= 45 and vad.dominance >= 0:
            return DisplayExpression.ANGRY
        if vad.arousal >= 25:
            return DisplayExpression.ANXIOUS
        return DisplayExpression.SAD
    return DisplayExpression.NEUTRAL


def map_mood_snapshot(snapshot: MoodSnapshot) -> DisplayState:
    expression = _from_family(snapshot) or _from_vad(snapshot)
    raw_energy = (snapshot.current_vad.arousal + 100) / 2
    energy = int((raw_energy + 5) // 10) * 10
    return DisplayState(
        snapshot.version,
        expression,
        "#FFFFFF",
        _COLORS[expression],
        max(0, min(100, energy)),
    )


__all__ = ("map_mood_snapshot",)
