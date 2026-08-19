#include "mood_face.h"

#include "lvgl.h"
#include "mood_text.h"

#define TEXT_SCALE 512
#define RENDER_INTERVAL_MS 80U

static lv_obj_t *screen;
static lv_obj_t *label;
static mood_state_t current_state;
static uint32_t last_tick_ms;
static uint32_t last_render_ms;
static uint32_t expression_started_ms;

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

static uint32_t dim_rgb(uint32_t rgb, uint8_t opacity)
{
    uint32_t red = ((rgb >> 16) & 0xffU) * opacity / 255U;
    uint32_t green = ((rgb >> 8) & 0xffU) * opacity / 255U;
    uint32_t blue = (rgb & 0xffU) * opacity / 255U;
    return (red << 16) | (green << 8) | blue;
}

void mood_face_init(void)
{
    screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    label = lv_label_create(screen);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_48, 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_transform_scale_x(label, TEXT_SCALE, 0);
    lv_obj_set_style_transform_scale_y(label, TEXT_SCALE, 0);
    mood_face_offline();
}

void mood_face_apply(const mood_state_t *state)
{
    current_state = *state;
    expression_started_ms = last_tick_ms;
    last_render_ms = last_tick_ms - RENDER_INTERVAL_MS;
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
    if (elapsed_ms - last_render_ms < RENDER_INTERVAL_MS) {
        return;
    }
    last_render_ms = elapsed_ms;
    mood_text_frame_t frame;
    mood_text_frame(current_state.face, current_state.energy,
                    elapsed_ms - expression_started_ms, &frame);
    uint32_t color = lift_rgb(current_state.foreground_rgb, frame.color_lift);
    lv_label_set_text_static(label, frame.text);
    lv_obj_set_style_text_color(label, lv_color_hex(dim_rgb(color, frame.opacity)), 0);
    lv_obj_center(label);
}
