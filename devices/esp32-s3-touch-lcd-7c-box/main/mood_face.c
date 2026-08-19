#include "mood_face.h"

#include "lvgl.h"
#include "mood_animation.h"

static lv_obj_t *screen;
static lv_obj_t *left_eye;
static lv_obj_t *right_eye;
static lv_obj_t *left_eye_cutout;
static lv_obj_t *right_eye_cutout;
static lv_obj_t *left_pupil;
static lv_obj_t *right_pupil;
static lv_obj_t *mouth;
static lv_obj_t *mouth_cutout;
static lv_obj_t *left_cheek;
static lv_obj_t *right_cheek;
static lv_obj_t *accent;
static mood_state_t current_state;
static uint32_t last_tick_ms;
static uint32_t animation_started_ms;

static uint32_t lift_rgb(uint32_t rgb, uint8_t percent)
{
    uint32_t red = (rgb >> 16) & 0xffU;
    uint32_t green = (rgb >> 8) & 0xffU;
    uint32_t blue = rgb & 0xffU;
    red += (255U - red) * percent / 100U;
    green += (255U - green) * percent / 100U;
    blue += (255U - blue) * percent / 100U;
    return (red << 16) | (green << 8) | blue;
}

static void hidden(lv_obj_t *object, bool value)
{
    if (value) {
        lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_remove_flag(object, LV_OBJ_FLAG_HIDDEN);
    }
}

static void rounded_block(
    lv_obj_t *object,
    int width,
    int height,
    int x,
    int y
)
{
    lv_obj_set_size(object, width, height);
    lv_obj_align(object, LV_ALIGN_CENTER, x, y);
    lv_obj_set_style_radius(object, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(object, 0, 0);
    lv_obj_set_style_pad_all(object, 0, 0);
}

static void apply_eye(
    lv_obj_t *eye,
    lv_obj_t *cutout,
    int width,
    int height,
    int x,
    int y,
    int rotation,
    int curve,
    lv_color_t foreground,
    lv_color_t background
)
{
    rounded_block(eye, width, height, x, y);
    lv_obj_set_style_bg_color(eye, foreground, 0);
    lv_obj_set_style_transform_rotation(eye, rotation, 0);
    hidden(cutout, curve == 0);
    if (curve == 0) {
        return;
    }
    int cutout_y = y;
    if (curve != 2) {
        cutout_y += curve < 0 ? height / 3 : -height / 3;
    }
    rounded_block(cutout, width - 12, height - 10, x, cutout_y);
    lv_obj_set_style_bg_color(cutout, background, 0);
    lv_obj_set_style_transform_rotation(cutout, rotation, 0);
}

static void apply_frame(const mood_animation_frame_t *frame)
{
    uint32_t animated_foreground = lift_rgb(
        current_state.foreground_rgb, frame->color_lift
    );
    lv_color_t foreground = lv_color_hex(animated_foreground);
    lv_color_t background = lv_color_black();
    lv_obj_set_style_bg_color(screen, background, 0);

    apply_eye(
        left_eye,
        left_eye_cutout,
        frame->left_eye_width,
        frame->left_eye_height,
        frame->left_eye_x,
        frame->left_eye_y,
        frame->left_eye_rotation,
        frame->left_eye_curve,
        foreground,
        background
    );
    apply_eye(
        right_eye,
        right_eye_cutout,
        frame->right_eye_width,
        frame->right_eye_height,
        frame->right_eye_x,
        frame->right_eye_y,
        frame->right_eye_rotation,
        frame->right_eye_curve,
        foreground,
        background
    );

    hidden(left_pupil, !frame->pupils_visible);
    hidden(right_pupil, !frame->pupils_visible);
    if (frame->pupils_visible) {
        rounded_block(
            left_pupil,
            frame->pupil_size,
            frame->pupil_size,
            frame->left_eye_x + frame->pupil_x,
            frame->left_eye_y + frame->pupil_y
        );
        rounded_block(
            right_pupil,
            frame->pupil_size,
            frame->pupil_size,
            frame->right_eye_x + frame->pupil_x,
            frame->right_eye_y + frame->pupil_y
        );
        lv_obj_set_style_bg_color(left_pupil, background, 0);
        lv_obj_set_style_bg_color(right_pupil, background, 0);
    }

    rounded_block(
        mouth,
        frame->mouth_width,
        frame->mouth_height,
        frame->mouth_x,
        frame->mouth_y
    );
    lv_obj_set_style_bg_color(mouth, foreground, 0);
    hidden(mouth_cutout, frame->mouth_curve == 0);
    if (frame->mouth_curve != 0) {
        int inset = frame->mouth_height / 3;
        int cutout_y = frame->mouth_y;
        if (frame->mouth_curve != 2) {
            cutout_y += frame->mouth_curve > 0 ? -inset : inset;
        }
        rounded_block(
            mouth_cutout,
            frame->mouth_width - 22,
            frame->mouth_height - 14,
            frame->mouth_x,
            cutout_y
        );
        lv_obj_set_style_bg_color(mouth_cutout, background, 0);
    }

    bool cheeks_visible = frame->cheek_opacity > 0;
    hidden(left_cheek, !cheeks_visible);
    hidden(right_cheek, !cheeks_visible);
    if (cheeks_visible) {
        rounded_block(left_cheek, 78, 8, -225, frame->cheek_y);
        rounded_block(right_cheek, 78, 8, 225, frame->cheek_y);
        lv_obj_set_style_bg_color(left_cheek, foreground, 0);
        lv_obj_set_style_bg_color(right_cheek, foreground, 0);
        uint8_t cheek_opacity = (uint8_t)(
            (uint16_t)frame->cheek_opacity * frame->face_opacity / 255U
        );
        lv_obj_set_style_bg_opa(left_cheek, cheek_opacity, 0);
        lv_obj_set_style_bg_opa(right_cheek, cheek_opacity, 0);
    }

    hidden(accent, !frame->accent_visible);
    if (frame->accent_visible) {
        rounded_block(
            accent,
            frame->accent_width,
            frame->accent_height,
            frame->accent_x,
            frame->accent_y
        );
        lv_obj_set_style_bg_color(accent, foreground, 0);
    }

    lv_obj_set_style_opa(left_eye, frame->face_opacity, 0);
    lv_obj_set_style_opa(right_eye, frame->face_opacity, 0);
    lv_obj_set_style_opa(left_eye_cutout, frame->face_opacity, 0);
    lv_obj_set_style_opa(right_eye_cutout, frame->face_opacity, 0);
    lv_obj_set_style_opa(mouth, frame->face_opacity, 0);
    lv_obj_set_style_opa(left_pupil, frame->face_opacity, 0);
    lv_obj_set_style_opa(right_pupil, frame->face_opacity, 0);
    lv_obj_set_style_opa(mouth_cutout, frame->face_opacity, 0);
    lv_obj_set_style_opa(accent, frame->face_opacity, 0);
}

static lv_obj_t *face_object(void)
{
    lv_obj_t *object = lv_obj_create(screen);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_border_width(object, 0, 0);
    lv_obj_set_style_pad_all(object, 0, 0);
    return object;
}

void mood_face_init(void)
{
    screen = lv_screen_active();
    left_eye = face_object();
    right_eye = face_object();
    left_eye_cutout = face_object();
    right_eye_cutout = face_object();
    left_pupil = face_object();
    right_pupil = face_object();
    mouth = face_object();
    mouth_cutout = face_object();
    left_cheek = face_object();
    right_cheek = face_object();
    accent = face_object();
    mood_face_offline();
}

void mood_face_apply(const mood_state_t *state)
{
    current_state = *state;
    animation_started_ms = last_tick_ms;
}

void mood_face_offline(void)
{
    const mood_state_t offline = {
        .face = MOOD_FACE_OFFLINE,
        .foreground_rgb = 0x3A3F47,
        .background_rgb = 0x000000,
        .energy = 0,
    };
    mood_face_apply(&offline);
}

void mood_face_tick(uint32_t elapsed_ms)
{
    last_tick_ms = elapsed_ms;
    mood_animation_frame_t frame;
    mood_animation_frame(
        current_state.face,
        current_state.energy,
        elapsed_ms - animation_started_ms,
        &frame
    );
    apply_frame(&frame);
}
