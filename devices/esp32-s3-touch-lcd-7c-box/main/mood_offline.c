#include "mood_offline.h"

#define MOOD_OFFLINE_AFTER_US (30LL * 1000 * 1000)

void mood_offline_init(mood_offline_state_t *state)
{
    state->last_state_us = 0;
    state->offline = true;
}

void mood_offline_received_state(mood_offline_state_t *state, int64_t now_us)
{
    state->last_state_us = now_us;
    state->offline = false;
}

bool mood_offline_tick(mood_offline_state_t *state, int64_t now_us)
{
    if (!state->offline && now_us - state->last_state_us > MOOD_OFFLINE_AFTER_US) {
        state->last_state_us = 0;
        state->offline = true;
        return true;
    }
    return false;
}
