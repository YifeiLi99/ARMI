#include <assert.h>
#include <string.h>

#include "mood_animation.h"
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

static void test_every_online_face_has_a_repeatable_frame_animation(void)
{
    for (mood_face_t face = MOOD_FACE_JOY; face <= MOOD_FACE_NEUTRAL; face++) {
        mood_animation_frame_t first;
        mood_animation_frame_t same_frame;
        mood_animation_frame_t later;
        mood_animation_frame(face, 70, 0, &first);
        mood_animation_frame(face, 70, 70, &same_frame);
        mood_animation_frame(face, 70, 800, &later);
        assert(memcmp(&first, &same_frame, sizeof(first)) == 0);
        assert(memcmp(&first, &later, sizeof(first)) != 0);
        assert(first.face_opacity < 255);
        mood_animation_frame(face, 70, 400, &later);
        assert(later.face_opacity == 255);
    }
}

static void test_expression_specific_accents_are_not_generic_breathing(void)
{
    mood_animation_frame_t joy;
    mood_animation_frame_t sadness;
    mood_animation_frame_t anxious;
    mood_animation_frame_t shame;
    mood_animation_frame(MOOD_FACE_JOY, 60, 800, &joy);
    mood_animation_frame(MOOD_FACE_SADNESS, 60, 800, &sadness);
    mood_animation_frame(MOOD_FACE_ANXIETY, 60, 800, &anxious);
    mood_animation_frame(MOOD_FACE_SHAME, 60, 800, &shame);
    assert(joy.mouth == MOOD_MOUTH_OPEN_SMILE);
    assert(joy.cheek_opacity > 0);
    assert(sadness.mouth == MOOD_MOUTH_FROWN);
    assert(sadness.accent == MOOD_ACCENT_TEAR);
    assert(anxious.accent == MOOD_ACCENT_SWEAT);
    assert(shame.cheek_opacity > joy.cheek_opacity);
}

static void test_energy_changes_motion_but_offline_remains_closed(void)
{
    mood_animation_frame_t low;
    mood_animation_frame_t high;
    mood_animation_frame_t offline_first;
    mood_animation_frame_t offline_later;
    mood_animation_frame(MOOD_FACE_SURPRISE, 10, 800, &low);
    mood_animation_frame(MOOD_FACE_SURPRISE, 100, 800, &high);
    assert(high.eye_scale > low.eye_scale);
    assert(high.color_lift > low.color_lift);
    mood_animation_frame(MOOD_FACE_OFFLINE, 0, 0, &offline_first);
    mood_animation_frame(MOOD_FACE_OFFLINE, 0, 4000, &offline_later);
    assert(memcmp(&offline_first, &offline_later, sizeof(offline_first)) == 0);
    assert(offline_first.left_eye == MOOD_EYE_FLAT);
    assert(offline_first.right_eye == MOOD_EYE_FLAT);
    assert(offline_first.mouth == MOOD_MOUTH_NONE);
}

int main(void)
{
    test_offline_state();
    test_protocol_state();
    test_every_online_face_has_a_repeatable_frame_animation();
    test_expression_specific_accents_are_not_generic_breathing();
    test_energy_changes_motion_but_offline_remains_closed();
    return 0;
}
