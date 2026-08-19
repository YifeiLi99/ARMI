#include "mood_protocol.h"

#include <stdio.h>
#include <string.h>

#include "cJSON.h"

static bool copy_text(char *target, const cJSON *value)
{
    if (!cJSON_IsString(value) || value->valuestring == NULL) {
        return false;
    }
    size_t length = strlen(value->valuestring);
    if (length == 0 || length > MOOD_ID_MAX_BYTES) {
        return false;
    }
    memcpy(target, value->valuestring, length + 1);
    return true;
}

static bool parse_color(const cJSON *value, uint32_t *target)
{
    unsigned int parsed = 0;
    if (!cJSON_IsString(value) || strlen(value->valuestring) != 7 ||
        value->valuestring[0] != '#' ||
        sscanf(value->valuestring + 1, "%06x", &parsed) != 1) {
        return false;
    }
    *target = parsed;
    return true;
}

static bool parse_face(const char *value, mood_face_t *face)
{
    static const char *names[] = {
        "face_01", "face_02", "face_03", "face_04", "face_05", "face_06",
        "face_07", "face_08", "face_09", "face_10", "face_11", "face_12",
        "face_13", "face_14", "face_15", "face_16", "face_17", "face_18",
        "face_19", "face_20", "neutral", "offline",
    };
    for (size_t index = 0; index < sizeof(names) / sizeof(names[0]); ++index) {
        if (strcmp(value, names[index]) == 0) {
            *face = (mood_face_t)index;
            return true;
        }
    }
    return false;
}

mood_parse_result_t mood_protocol_parse(const char *frame, size_t length)
{
    mood_parse_result_t result = {.kind = MOOD_PARSE_REJECT, .reject_code = "invalid_frame"};
    if (frame == NULL || length == 0 || length > MOOD_FRAME_MAX_BYTES ||
        frame[length - 1] != '\n') {
        return result;
    }
    cJSON *root = cJSON_ParseWithLength(frame, length - 1);
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return result;
    }
    const cJSON *protocol = cJSON_GetObjectItemCaseSensitive(root, "protocol_version");
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    if (!cJSON_IsString(protocol) || !cJSON_IsString(type) ||
        strcmp(protocol->valuestring, MOOD_PROTOCOL_VERSION) != 0) {
        result.reject_code = "protocol_mismatch";
        cJSON_Delete(root);
        return result;
    }
    if (strcmp(type->valuestring, "ping") == 0) {
        if (cJSON_GetArraySize(root) == 3 &&
            copy_text(result.ping_id, cJSON_GetObjectItemCaseSensitive(root, "ping_id"))) {
            result.kind = MOOD_PARSE_PING;
        }
        cJSON_Delete(root);
        return result;
    }
    if (strcmp(type->valuestring, "state") != 0) {
        result.reject_code = "unsupported_type";
        cJSON_Delete(root);
        return result;
    }
    result.reject_code = "invalid_state";
    const cJSON *mood_version = cJSON_GetObjectItemCaseSensitive(root, "mood_version");
    const cJSON *expression = cJSON_GetObjectItemCaseSensitive(root, "expression");
    const cJSON *energy = cJSON_GetObjectItemCaseSensitive(root, "energy");
    const cJSON *validity = cJSON_GetObjectItemCaseSensitive(root, "valid_for_seconds");
    bool valid = cJSON_GetArraySize(root) == 9 && copy_text(
        result.state.state_id, cJSON_GetObjectItemCaseSensitive(root, "state_id")
    ) && cJSON_IsNumber(mood_version) && mood_version->valuedouble >= 1 &&
        mood_version->valuedouble <= UINT32_MAX &&
        mood_version->valuedouble == (uint32_t)mood_version->valuedouble &&
        cJSON_IsString(expression) &&
        parse_face(expression->valuestring, &result.state.face) &&
        parse_color(cJSON_GetObjectItemCaseSensitive(root, "foreground"),
                    &result.state.foreground_rgb) &&
        parse_color(cJSON_GetObjectItemCaseSensitive(root, "background"),
                    &result.state.background_rgb) &&
        result.state.background_rgb == 0x000000U &&
        cJSON_IsNumber(energy) && energy->valuedouble >= 0 && energy->valuedouble <= 100 &&
        energy->valuedouble == (uint8_t)energy->valuedouble &&
        cJSON_IsNumber(validity) && validity->valuedouble == 30;
    if (valid) {
        result.state.mood_version = (uint32_t)mood_version->valuedouble;
        result.state.energy = (uint8_t)energy->valuedouble;
        result.state.valid_for_seconds = 30;
        result.kind = MOOD_PARSE_STATE;
        result.reject_code = NULL;
    }
    cJSON_Delete(root);
    return result;
}

static size_t render(char *target, size_t capacity, const char *format,
                     const char *first, const char *second)
{
    int written = snprintf(target, capacity, format, first, second);
    return written > 0 && (size_t)written < capacity && written <= MOOD_FRAME_MAX_BYTES
        ? (size_t)written : 0;
}

size_t mood_protocol_hello(char *target, size_t capacity, const char *boot_id)
{
    return render(target, capacity,
        "{\"boot_id\":\"%s\",\"device_id\":\"armi-mood-window-7c-1\","
        "\"firmware_version\":\"0.2.0\",\"protocol_version\":\"%s\","
        "\"type\":\"hello\"}\n", boot_id, MOOD_PROTOCOL_VERSION);
}

size_t mood_protocol_ack(char *target, size_t capacity, const char *state_id,
                         const char *status)
{
    if (strcmp(status, "applied") != 0 && strcmp(status, "invalid_state") != 0) {
        return 0;
    }
    int written = snprintf(target, capacity,
        "{\"protocol_version\":\"%s\",\"state_id\":\"%s\","
        "\"status\":\"%s\",\"type\":\"ack\"}\n",
        MOOD_PROTOCOL_VERSION, state_id, status);
    return written > 0 && (size_t)written < capacity && written <= MOOD_FRAME_MAX_BYTES
        ? (size_t)written : 0;
}

size_t mood_protocol_pong(char *target, size_t capacity, const char *ping_id)
{
    return render(target, capacity,
        "{\"ping_id\":\"%s\",\"protocol_version\":\"%s\",\"type\":\"pong\"}\n",
        ping_id, MOOD_PROTOCOL_VERSION);
}
