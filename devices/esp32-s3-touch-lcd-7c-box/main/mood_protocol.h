#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MOOD_PROTOCOL_VERSION "armi.mood-display.v2"
#define MOOD_FRAME_MAX_BYTES 512
#define MOOD_ID_MAX_BYTES 64

typedef enum {
    MOOD_FACE_JOY,
    MOOD_FACE_CONTENTMENT,
    MOOD_FACE_INTEREST,
    MOOD_FACE_HOPE,
    MOOD_FACE_RELIEF,
    MOOD_FACE_AFFECTION,
    MOOD_FACE_GRATITUDE,
    MOOD_FACE_PRIDE,
    MOOD_FACE_SURPRISE,
    MOOD_FACE_SADNESS,
    MOOD_FACE_FEAR,
    MOOD_FACE_ANXIETY,
    MOOD_FACE_ANGER,
    MOOD_FACE_FRUSTRATION,
    MOOD_FACE_DISGUST,
    MOOD_FACE_SHAME,
    MOOD_FACE_GUILT,
    MOOD_FACE_JEALOUSY,
    MOOD_FACE_BOREDOM,
    MOOD_FACE_CONFUSION,
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
