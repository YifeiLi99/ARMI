#pragma once

#include <stdint.h>

#include "mood_protocol.h"

typedef struct {
    const char *text;
    uint32_t asset_offset;
    uint16_t width;
    uint16_t height;
} mood_text_asset_t;

typedef struct {
    const mood_text_asset_t *asset;
    uint8_t color_lift;
    uint8_t opacity;
} mood_text_frame_t;

const mood_text_asset_t *mood_text_asset(mood_face_t face);
const char *mood_text_expression(mood_face_t face);
void mood_text_frame(
    mood_face_t face,
    uint8_t energy,
    uint32_t elapsed_ms,
    mood_text_frame_t *target
);
