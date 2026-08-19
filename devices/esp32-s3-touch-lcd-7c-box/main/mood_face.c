#include "mood_face.h"

#include <stddef.h>
#include <stdlib.h>

#include "lvgl.h"
#include "mood_text.h"

#define RENDER_INTERVAL_MS 80U
#define MOOD_FACE_COUNT ((size_t)MOOD_FACE_OFFLINE + 1U)

extern const uint8_t mood_text_assets_start[]
    asm("_binary_mood_text_assets_bin_start");
extern const uint8_t mood_text_assets_end[]
    asm("_binary_mood_text_assets_bin_end");

static lv_obj_t *screen;
static lv_obj_t *image;
static lv_image_dsc_t image_descriptors[MOOD_FACE_COUNT];
static mood_state_t current_state;
static uint32_t last_tick_ms;
static uint32_t last_render_ms;
static uint32_t expression_started_ms;
static mood_face_t displayed_face = (mood_face_t)(MOOD_FACE_OFFLINE + 1);

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

static void initialize_descriptors(void)
{
    size_t embedded_size = (size_t)(mood_text_assets_end - mood_text_assets_start);
    for (size_t index = 0; index < MOOD_FACE_COUNT; index++) {
        const mood_text_asset_t *asset = mood_text_asset((mood_face_t)index);
        size_t asset_size = (size_t)asset->width * asset->height;
        if (asset->asset_offset > embedded_size ||
            asset_size > embedded_size - asset->asset_offset) {
            abort();
        }
        image_descriptors[index] = (lv_image_dsc_t){
            .header = {
                .magic = LV_IMAGE_HEADER_MAGIC,
                .cf = LV_COLOR_FORMAT_A8,
                .flags = 0,
                .w = asset->width,
                .h = asset->height,
                .stride = asset->width,
            },
            .data_size = (uint32_t)asset_size,
            .data = mood_text_assets_start + asset->asset_offset,
        };
    }
}

void mood_face_init(void)
{
    screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    initialize_descriptors();
    image = lv_image_create(screen);
    lv_obj_set_style_image_recolor_opa(image, LV_OPA_COVER, 0);
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
    if (displayed_face != current_state.face) {
        displayed_face = current_state.face;
        lv_image_set_src(image, &image_descriptors[displayed_face]);
        lv_obj_center(image);
    }
    uint32_t color = lift_rgb(current_state.foreground_rgb, frame.color_lift);
    lv_obj_set_style_image_recolor(image, lv_color_hex(color), 0);
    lv_obj_set_style_opa(image, frame.opacity, 0);
}
