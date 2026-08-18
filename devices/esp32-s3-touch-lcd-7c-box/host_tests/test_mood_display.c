#include <assert.h>
#include <string.h>

#include "mood_offline.h"
#include "mood_protocol.h"

static void test_offline_state(void)
{
    mood_offline_state_t state;
    mood_offline_init(&state);
    assert(state.offline);
    mood_offline_received_state(&state, 100);
    assert(!mood_offline_tick(&state, 30000100));
    assert(mood_offline_tick(&state, 30000101));
    assert(state.offline);
    assert(!mood_offline_tick(&state, 60000102));
}

static void test_protocol_state(void)
{
    const char *valid =
        "{\"background\":\"#F6C85F\",\"energy\":80,\"expression\":\"happy\","
        "\"foreground\":\"#FFFFFF\",\"mood_version\":7,"
        "\"protocol_version\":\"armi.mood-display.v1\",\"state_id\":\"state-1\","
        "\"type\":\"state\",\"valid_for_seconds\":30}\n";
    mood_parse_result_t result = mood_protocol_parse(valid, strlen(valid));
    assert(result.kind == MOOD_PARSE_STATE);
    assert(result.state.face == MOOD_FACE_HAPPY);
    assert(result.state.energy == 80);

    const char *unknown_field =
        "{\"background\":\"#F6C85F\",\"energy\":80,\"expression\":\"happy\","
        "\"foreground\":\"#FFFFFF\",\"mood_version\":7,"
        "\"protocol_version\":\"armi.mood-display.v1\",\"state_id\":\"state-1\","
        "\"type\":\"state\",\"unknown\":true,\"valid_for_seconds\":30}\n";
    result = mood_protocol_parse(unknown_field, strlen(unknown_field));
    assert(result.kind == MOOD_PARSE_REJECT);
    assert(strcmp(result.reject_code, "invalid_state") == 0);
}

int main(void)
{
    test_offline_state();
    test_protocol_state();
    return 0;
}
