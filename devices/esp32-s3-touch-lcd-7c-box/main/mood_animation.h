#pragma once

#include <stdint.h>

#include "mood_protocol.h"

typedef enum {
    MOOD_EYE_DOT,
    MOOD_EYE_FLAT,
    MOOD_EYE_CAP,
    MOOD_EYE_SOFT,
    MOOD_EYE_RAISED,
    MOOD_EYE_PROUD,
    MOOD_EYE_STAR,
    MOOD_EYE_HEART,
    MOOD_EYE_RING,
    MOOD_EYE_RING_DOT,
    MOOD_EYE_GREATER,
    MOOD_EYE_LESS,
    MOOD_EYE_SAD_LEFT,
    MOOD_EYE_SAD_RIGHT,
    MOOD_EYE_GUILT_LEFT,
    MOOD_EYE_GUILT_RIGHT,
    MOOD_EYE_HALF,
} mood_eye_glyph_t;

typedef enum {
    MOOD_MOUTH_NONE,
    MOOD_MOUTH_SMILE,
    MOOD_MOUTH_PROUD_SMILE,
    MOOD_MOUTH_SMALL_SMILE,
    MOOD_MOUTH_SMALL_FROWN,
    MOOD_MOUTH_FROWN,
    MOOD_MOUTH_OMEGA,
    MOOD_MOUTH_WAVE,
    MOOD_MOUTH_TEETH,
    MOOD_MOUTH_SKEW_FROWN,
    MOOD_MOUTH_FLAT,
    MOOD_MOUTH_OPEN,
    MOOD_MOUTH_OPEN_SMILE,
} mood_mouth_glyph_t;

typedef enum {
    MOOD_ACCENT_NONE,
    MOOD_ACCENT_TEAR,
    MOOD_ACCENT_SWEAT,
    MOOD_ACCENT_SPARKLE,
    MOOD_ACCENT_RISE,
    MOOD_ACCENT_EXHALE,
    MOOD_ACCENT_STRESS,
    MOOD_ACCENT_QUESTION,
} mood_accent_glyph_t;

typedef struct {
    mood_eye_glyph_t left_eye;
    mood_eye_glyph_t right_eye;
    mood_mouth_glyph_t mouth;
    int16_t eye_y;
    int16_t eye_spread;
    int16_t eye_shift_x;
    int16_t eye_scale;
    int16_t mouth_y;
    int16_t mouth_scale_x;
    int16_t mouth_scale_y;
    int16_t face_x;
    int16_t face_y;
    uint8_t cheek_opacity;
    mood_accent_glyph_t accent;
    int16_t accent_x;
    int16_t accent_y;
    uint8_t color_lift;
    uint8_t face_opacity;
} mood_animation_frame_t;

void mood_animation_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_animation_frame_t *target
);
