#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int64_t last_state_us;
    bool offline;
} mood_offline_state_t;

void mood_offline_init(mood_offline_state_t *state);
void mood_offline_received_state(mood_offline_state_t *state, int64_t now_us);
bool mood_offline_tick(mood_offline_state_t *state, int64_t now_us);
