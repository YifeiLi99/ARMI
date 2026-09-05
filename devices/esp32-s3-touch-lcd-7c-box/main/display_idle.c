#include "display_idle.h"

void display_idle_activity(display_idle_t *idle, int64_t now_us)
{
    idle->last_activity_us = now_us;
}

uint8_t display_idle_brightness(const display_idle_t *idle, int64_t now_us)
{
    int64_t elapsed = now_us - idle->last_activity_us;
    if (elapsed >= 120LL * 1000 * 1000) {
        return 0;
    }
    if (elapsed >= 30LL * 1000 * 1000) {
        return DISPLAY_BRIGHTNESS_DIM;
    }
    return DISPLAY_BRIGHTNESS_NORMAL;
}

bool display_style_equal(const mood_state_t *left, const mood_state_t *right)
{
    return left->face == right->face &&
           left->foreground_rgb == right->foreground_rgb &&
           left->background_rgb == right->background_rgb &&
           left->energy == right->energy;
}
