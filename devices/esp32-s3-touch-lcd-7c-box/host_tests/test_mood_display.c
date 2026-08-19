#include <assert.h>
#include <string.h>

#include "mood_offline.h"
#include "mood_protocol.h"
#include "mood_text.h"

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
        "{\"background\":\"#000000\",\"energy\":80,\"expression\":\"face_01\","
        "\"foreground\":\"#F6C85F\",\"mood_version\":7,"
        "\"protocol_version\":\"armi.mood-display.v2\",\"state_id\":\"state-1\","
        "\"type\":\"state\",\"valid_for_seconds\":30}\n";
    mood_parse_result_t result = mood_protocol_parse(valid, strlen(valid));
    assert(result.kind == MOOD_PARSE_STATE);
    assert(result.state.face == MOOD_FACE_JOY);
    assert(result.state.energy == 80);

    const char *unknown_field =
        "{\"background\":\"#000000\",\"energy\":80,\"expression\":\"face_01\","
        "\"foreground\":\"#F6C85F\",\"mood_version\":7,"
        "\"protocol_version\":\"armi.mood-display.v2\",\"state_id\":\"state-1\","
        "\"type\":\"state\",\"unknown\":true,\"valid_for_seconds\":30}\n";
    result = mood_protocol_parse(unknown_field, strlen(unknown_field));
    assert(result.kind == MOOD_PARSE_REJECT);
    assert(strcmp(result.reject_code, "invalid_state") == 0);

    const char *non_black_background =
        "{\"background\":\"#FFFFFF\",\"energy\":80,\"expression\":\"face_01\","
        "\"foreground\":\"#F6C85F\",\"mood_version\":7,"
        "\"protocol_version\":\"armi.mood-display.v2\",\"state_id\":\"state-1\","
        "\"type\":\"state\",\"valid_for_seconds\":30}\n";
    result = mood_protocol_parse(non_black_background, strlen(non_black_background));
    assert(result.kind == MOOD_PARSE_REJECT);
    assert(strcmp(result.reject_code, "invalid_state") == 0);
}

static void test_every_face_has_a_unique_unicode_asset(void)
{
    uint32_t previous_end = 0;
    for (mood_face_t face = MOOD_FACE_JOY; face <= MOOD_FACE_OFFLINE; face++) {
        const mood_text_asset_t *asset = mood_text_asset(face);
        const char *expression = asset->text;
        assert(expression[0] != '\0');
        assert(asset->width > 0 && asset->width <= 720);
        assert(asset->height > 0 && asset->height <= 160);
        assert(asset->asset_offset == previous_end);
        previous_end = asset->asset_offset +
                       (uint32_t)asset->width * asset->height;
        for (mood_face_t previous = MOOD_FACE_JOY; previous < face; previous++) {
            assert(strcmp(expression, mood_text_expression(previous)) != 0);
        }
    }
}

static void test_transition_and_energy_only_change_text_appearance(void)
{
    mood_text_frame_t first;
    mood_text_frame_t low;
    mood_text_frame_t high;
    mood_text_frame_t offline_first;
    mood_text_frame_t offline_later;
    mood_text_frame(MOOD_FACE_SURPRISE, 10, 0, &first);
    mood_text_frame(MOOD_FACE_SURPRISE, 10, 800, &low);
    mood_text_frame(MOOD_FACE_SURPRISE, 100, 800, &high);
    assert(first.asset == low.asset);
    assert(first.opacity < 255);
    assert(low.opacity == 255);
    assert(high.color_lift > low.color_lift);
    mood_text_frame(MOOD_FACE_OFFLINE, 0, 0, &offline_first);
    mood_text_frame(MOOD_FACE_OFFLINE, 100, 4000, &offline_later);
    assert(memcmp(&offline_first, &offline_later, sizeof(offline_first)) == 0);
    assert(offline_first.opacity == 180);
}

int main(void)
{
    test_offline_state();
    test_protocol_state();
    test_every_face_has_a_unique_unicode_asset();
    test_transition_and_energy_only_change_text_appearance();
    return 0;
}
