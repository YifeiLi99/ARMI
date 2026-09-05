#include <assert.h>
#include <string.h>

#include "display_idle.h"

int main(void)
{
    display_idle_t idle;
    // Use uptime beyond a 32-bit millisecond rollover.
    const int64_t start = 5000000000000LL;
    display_idle_activity(&idle, start);
    assert(display_idle_brightness(&idle, start + 29999999) == 128);
    assert(display_idle_brightness(&idle, start + 30000000) == 26);
    assert(display_idle_brightness(&idle, start + 119999999) == 26);
    assert(display_idle_brightness(&idle, start + 120000000) == 0);
    display_idle_activity(&idle, start + 150000000);
    assert(display_idle_brightness(&idle, start + 150000000) == 128);
    assert(display_idle_brightness(&idle, start + 180000000) == 26);

    const mood_state_t original = {
        .state_id = "first", .mood_version = 1, .face = MOOD_FACE_JOY,
        .foreground_rgb = 0x00ffff, .energy = 70, .valid_for_seconds = 30,
    };
    mood_state_t next = original;
    strcpy(next.state_id, "heartbeat");
    next.mood_version++;
    next.valid_for_seconds = 20;
    assert(display_style_equal(&original, &next));
    next.face = MOOD_FACE_OFFLINE;
    assert(!display_style_equal(&original, &next));
    next = original;
    next.foreground_rgb++;
    assert(!display_style_equal(&original, &next));
    next = original;
    next.energy++;
    assert(!display_style_equal(&original, &next));
    next = original;
    next.background_rgb++;
    assert(!display_style_equal(&original, &next));
    return 0;
}
