#include "mood_face.h"

#include "lvgl.h"

static lv_obj_t *screen;
static lv_obj_t *left_eye;
static lv_obj_t *right_eye;
static lv_obj_t *mouth;
static uint8_t energy;
static int left_eye_base_height;
static int right_eye_base_height;
static int mouth_base_y;

static void geometry(mood_face_t face)
{
    int left_eye_width = 92;
    int right_eye_width = 92;
    int left_eye_height = 54;
    int right_eye_height = 54;
    int mouth_height = 18;
    int mouth_width = 180;
    int mouth_x = 0;
    int mouth_y = 105;
    if (face == MOOD_FACE_HAPPY) {
        mouth_width = 230;
        mouth_height = 55;
    } else if (face == MOOD_FACE_EXCITED) {
        left_eye_width = right_eye_width = 110;
        left_eye_height = right_eye_height = 70;
        mouth_width = 260;
        mouth_height = 70;
    } else if (face == MOOD_FACE_CALM) {
        left_eye_width = right_eye_width = 100;
        left_eye_height = right_eye_height = 12;
    } else if (face == MOOD_FACE_SAD) {
        left_eye_width = right_eye_width = 72;
        left_eye_height = right_eye_height = 42;
        mouth_width = 180;
        mouth_height = 10;
        mouth_y = 125;
    } else if (face == MOOD_FACE_ANXIOUS) {
        left_eye_width = right_eye_width = 64;
        left_eye_height = right_eye_height = 76;
        mouth_width = 120;
    } else if (face == MOOD_FACE_ANGRY) {
        left_eye_width = right_eye_width = 110;
        left_eye_height = right_eye_height = 34;
        mouth_width = 210;
        mouth_height = 25;
    } else if (face == MOOD_FACE_DISGUSTED) {
        left_eye_height = 52;
        right_eye_height = 24;
        mouth_width = 150;
        mouth_height = 22;
        mouth_x = 35;
    } else if (face == MOOD_FACE_EMBARRASSED) {
        left_eye_width = right_eye_width = 70;
        left_eye_height = right_eye_height = 42;
        mouth_width = 110;
    } else if (face == MOOD_FACE_OFFLINE) {
        left_eye_height = right_eye_height = 8;
        mouth_width = 150;
        mouth_height = 8;
    }
    left_eye_base_height = left_eye_height;
    right_eye_base_height = right_eye_height;
    lv_obj_set_size(left_eye, left_eye_width, left_eye_height);
    lv_obj_set_size(right_eye, right_eye_width, right_eye_height);
    lv_obj_align(left_eye, LV_ALIGN_CENTER, -145, -65);
    lv_obj_align(right_eye, LV_ALIGN_CENTER, 145, -65);
    lv_obj_set_size(mouth, mouth_width, mouth_height);
    lv_obj_align(mouth, LV_ALIGN_CENTER, mouth_x, mouth_y);
    mouth_base_y = lv_obj_get_y(mouth);
}

void mood_face_init(void)
{
    screen = lv_screen_active();
    left_eye = lv_obj_create(screen);
    right_eye = lv_obj_create(screen);
    mouth = lv_obj_create(screen);
    lv_obj_remove_flag(left_eye, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(right_eye, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(mouth, LV_OBJ_FLAG_SCROLLABLE);
    mood_face_offline();
}

void mood_face_apply(const mood_state_t *state)
{
    energy = state->energy;
    lv_color_t foreground = lv_color_hex(state->foreground_rgb);
    lv_obj_set_style_bg_color(screen, lv_color_hex(state->background_rgb), 0);
    lv_obj_set_style_bg_color(left_eye, foreground, 0);
    lv_obj_set_style_bg_color(right_eye, foreground, 0);
    lv_obj_set_style_bg_color(mouth, foreground, 0);
    lv_obj_set_style_radius(left_eye, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_radius(right_eye, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_radius(mouth, LV_RADIUS_CIRCLE, 0);
    geometry(state->face);
}

void mood_face_offline(void)
{
    const mood_state_t offline = {
        .face = MOOD_FACE_OFFLINE, .foreground_rgb = 0xFFFFFF,
        .background_rgb = 0x3A3F47, .energy = 0,
    };
    mood_face_apply(&offline);
}

void mood_face_tick(uint32_t elapsed_ms)
{
    uint32_t phase = elapsed_ms % 4000;
    int offset = (int)((phase < 2000 ? phase : 4000 - phase) * energy / 20000);
    lv_obj_set_y(mouth, mouth_base_y + offset - energy / 20);
    if (elapsed_ms % 5000 < 120 && energy > 0) {
        lv_obj_set_height(left_eye, 8);
        lv_obj_set_height(right_eye, 8);
    } else {
        lv_obj_set_height(left_eye, left_eye_base_height);
        lv_obj_set_height(right_eye, right_eye_base_height);
    }
}
