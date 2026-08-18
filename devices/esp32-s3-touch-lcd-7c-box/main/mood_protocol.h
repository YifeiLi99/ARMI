#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MOOD_PROTOCOL_VERSION "armi.mood-display.v1"
#define MOOD_FRAME_MAX_BYTES 512
#define MOOD_ID_MAX_BYTES 64

typedef enum {
    MOOD_FACE_HAPPY,
    MOOD_FACE_EXCITED,
    MOOD_FACE_CALM,
    MOOD_FACE_SAD,
    MOOD_FACE_ANXIOUS,
    MOOD_FACE_ANGRY,
    MOOD_FACE_DISGUSTED,
    MOOD_FACE_EMBARRASSED,
    MOOD_FACE_NEUTRAL,
    MOOD_FACE_OFFLINE,
} mood_face_t;

typedef struct {
    char state_id[MOOD_ID_MAX_BYTES + 1];
    uint32_t mood_version;
    mood_face_t face;
    uint32_t foreground_rgb;
    uint32_t background_rgb;
    uint8_t energy;
    uint8_t valid_for_seconds;
} mood_state_t;

typedef enum {
    MOOD_PARSE_STATE,
    MOOD_PARSE_PING,
    MOOD_PARSE_REJECT,
} mood_parse_kind_t;

typedef struct {
    mood_parse_kind_t kind;
    mood_state_t state;
    char ping_id[MOOD_ID_MAX_BYTES + 1];
    const char *reject_code;
} mood_parse_result_t;

mood_parse_result_t mood_protocol_parse(const char *frame, size_t length);
size_t mood_protocol_hello(char *target, size_t capacity, const char *boot_id);
size_t mood_protocol_ack(
    char *target, size_t capacity, const char *state_id, const char *status
);
size_t mood_protocol_pong(char *target, size_t capacity, const char *ping_id);
