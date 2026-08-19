#pragma once

#include <stdint.h>

#include "mood_protocol.h"

typedef struct {
    const char *text;
    uint8_t color_lift;
    uint8_t opacity;
} mood_text_frame_t;

const char *mood_text_expression(mood_face_t face);
void mood_text_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_text_frame_t *target
);
