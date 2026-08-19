#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "mood_protocol.h"

typedef struct {
    int16_t left_eye_width;
    int16_t left_eye_height;
    int16_t left_eye_x;
    int16_t left_eye_y;
    int16_t right_eye_width;
    int16_t right_eye_height;
    int16_t right_eye_x;
    int16_t right_eye_y;
    int16_t pupil_size;
    int16_t pupil_x;
    int16_t pupil_y;
    bool pupils_visible;
    int16_t mouth_width;
    int16_t mouth_height;
    int16_t mouth_x;
    int16_t mouth_y;
    int8_t mouth_curve;
    uint8_t cheek_opacity;
    int16_t cheek_y;
    bool accent_visible;
    int16_t accent_width;
    int16_t accent_height;
    int16_t accent_x;
    int16_t accent_y;
    uint8_t background_lift;
    uint8_t face_opacity;
} mood_animation_frame_t;

void mood_animation_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_animation_frame_t *target
);
