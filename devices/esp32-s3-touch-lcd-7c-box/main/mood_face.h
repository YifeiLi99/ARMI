#pragma once

#include "mood_protocol.h"

void mood_face_init(void);
void mood_face_apply(const mood_state_t *state);
void mood_face_offline(void);
void mood_face_tick(uint32_t elapsed_ms);
