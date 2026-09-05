#pragma once

#include "mood_protocol.h"

#define DISPLAY_BRIGHTNESS_NORMAL 128U
#define DISPLAY_BRIGHTNESS_DIM 26U

typedef struct {
    int64_t last_activity_us;
} display_idle_t;

void display_idle_activity(display_idle_t *idle, int64_t now_us);
uint8_t display_idle_brightness(const display_idle_t *idle, int64_t now_us);
bool display_style_equal(const mood_state_t *left, const mood_state_t *right);
