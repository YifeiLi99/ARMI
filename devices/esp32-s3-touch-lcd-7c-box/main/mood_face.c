#include "mood_face.h"

#include <stdlib.h>

#include "esp_heap_caps.h"
#include "lvgl.h"
#include "mood_animation.h"

#define SCREEN_WIDTH 800
#define SCREEN_HEIGHT 480
#define LOGICAL_WIDTH 200
#define PIXEL_SCALE 4
#define COUNT(values) (sizeof(values) / sizeof((values)[0]))

typedef struct {
    int16_t x;
    int16_t y;
} point_t;

static lv_obj_t *screen;
static lv_obj_t *canvas;
static lv_color_t *canvas_buffer;
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

static uint32_t dim_rgb(uint32_t rgb, uint8_t opacity)
{
    uint32_t red = ((rgb >> 16) & 0xffU) * opacity / 255U;
    uint32_t green = ((rgb >> 8) & 0xffU) * opacity / 255U;
    uint32_t blue = (rgb & 0xffU) * opacity / 255U;
    return (red << 16) | (green << 8) | blue;
}

static void block(
    lv_layer_t *layer,
    int x,
    int y,
    int width,
    int height,
    lv_color_t color
)
{
    lv_draw_rect_dsc_t descriptor;
    lv_draw_rect_dsc_init(&descriptor);
    descriptor.bg_color = color;
    descriptor.bg_opa = LV_OPA_COVER;
    descriptor.border_width = 0;
    descriptor.radius = 0;
    lv_area_t area = {
        .x1 = x * PIXEL_SCALE,
        .y1 = y * PIXEL_SCALE,
        .x2 = (x + width) * PIXEL_SCALE - 1,
        .y2 = (y + height) * PIXEL_SCALE - 1,
    };
    lv_draw_rect(layer, &descriptor, &area);
}

static void pixel_line(
    lv_layer_t *layer,
    int x0,
    int y0,
    int x1,
    int y1,
    int thickness,
    lv_color_t color
)
{
    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    for (;;) {
        block(layer, x0 - thickness / 2, y0 - thickness / 2,
              thickness, thickness, color);
        if (x0 == x1 && y0 == y1) {
            break;
        }
        int twice = 2 * error;
        if (twice >= dy) {
            error += dy;
            x0 += sx;
        }
        if (twice <= dx) {
            error += dx;
            y0 += sy;
        }
    }
}

static void relative_path(
    lv_layer_t *layer,
    const point_t *points,
    size_t count,
    int cx,
    int cy,
    int scale_x,
    int scale_y,
    int thickness,
    lv_color_t color
)
{
    for (size_t index = 1; index < count; ++index) {
        pixel_line(
            layer,
            cx + points[index - 1].x * scale_x / 100,
            cy + points[index - 1].y * scale_y / 100,
            cx + points[index].x * scale_x / 100,
            cy + points[index].y * scale_y / 100,
            thickness,
            color
        );
    }
}

static void draw_eye(
    lv_layer_t *layer,
    mood_eye_glyph_t glyph,
    int cx,
    int cy,
    int scale,
    lv_color_t color
)
{
    static const point_t flat[] = {{-12, 0}, {12, 0}};
    static const point_t cap[] = {{-14, 5}, {-10, 1}, {-5, -2}, {0, -3}, {5, -2}, {10, 1}, {14, 5}};
    static const point_t soft[] = {{-11, 3}, {-6, 0}, {0, -2}, {6, 0}, {11, 3}};
    static const point_t raised[] = {{-12, 4}, {-6, 0}, {1, -3}, {7, -3}, {12, -1}};
    static const point_t proud[] = {{-12, 1}, {-4, -1}, {4, -1}, {12, 1}};
    static const point_t greater[] = {{-9, -8}, {2, 0}, {-9, 8}};
    static const point_t less[] = {{9, -8}, {-2, 0}, {9, 8}};
    static const point_t sad_left[] = {{-12, -3}, {-4, 2}, {5, 5}, {12, 5}};
    static const point_t sad_right[] = {{-12, 5}, {-5, 5}, {4, 2}, {12, -3}};
    static const point_t guilt_left[] = {{-11, -4}, {-7, 1}, {-2, 5}, {5, 6}, {11, 4}};
    static const point_t guilt_right[] = {{-11, 4}, {-5, 6}, {2, 5}, {7, 1}, {11, -4}};
    static const point_t half[] = {{-12, -2}, {-4, 3}, {5, 4}, {12, 1}};
    static const point_t heart[] = {{-10, -4}, {-7, -8}, {-2, -8}, {0, -4}, {2, -8}, {7, -8}, {10, -4}, {9, 1}, {0, 10}, {-9, 1}, {-10, -4}};
    static const point_t ring[] = {{-7, -9}, {7, -9}, {10, -6}, {10, 6}, {7, 9}, {-7, 9}, {-10, 6}, {-10, -6}, {-7, -9}};

    const point_t *path = NULL;
    size_t count = 0;
    int thickness = 2;
    switch (glyph) {
    case MOOD_EYE_DOT: {
        static const int widths[] = {3, 5, 7, 7, 7, 5, 3};
        for (int row = 0; row < 7; ++row) {
            block(layer, cx - widths[row] / 2, cy - 3 + row,
                  widths[row], 1, color);
        }
        return;
    }
    case MOOD_EYE_STAR:
        pixel_line(layer, cx, cy - 10, cx, cy + 10, 2, color);
        pixel_line(layer, cx - 10, cy, cx + 10, cy, 2, color);
        pixel_line(layer, cx - 7, cy - 7, cx + 7, cy + 7, 1, color);
        pixel_line(layer, cx + 7, cy - 7, cx - 7, cy + 7, 1, color);
        return;
    case MOOD_EYE_HEART:
        relative_path(layer, heart, COUNT(heart), cx, cy, scale, scale, 2, color);
        return;
    case MOOD_EYE_RING:
    case MOOD_EYE_RING_DOT:
        relative_path(layer, ring, COUNT(ring), cx, cy, scale, scale, 2, color);
        if (glyph == MOOD_EYE_RING_DOT) {
            int size = 5 * scale / 100;
            if (size < 3) size = 3;
            block(layer, cx - size / 2, cy - size / 2, size, size, color);
        }
        return;
    case MOOD_EYE_FLAT: path = flat; count = COUNT(flat); break;
    case MOOD_EYE_CAP: path = cap; count = COUNT(cap); break;
    case MOOD_EYE_SOFT: path = soft; count = COUNT(soft); break;
    case MOOD_EYE_RAISED: path = raised; count = COUNT(raised); break;
    case MOOD_EYE_PROUD: path = proud; count = COUNT(proud); break;
    case MOOD_EYE_GREATER: path = greater; count = COUNT(greater); thickness = 3; break;
    case MOOD_EYE_LESS: path = less; count = COUNT(less); thickness = 3; break;
    case MOOD_EYE_SAD_LEFT: path = sad_left; count = COUNT(sad_left); break;
    case MOOD_EYE_SAD_RIGHT: path = sad_right; count = COUNT(sad_right); break;
    case MOOD_EYE_GUILT_LEFT: path = guilt_left; count = COUNT(guilt_left); break;
    case MOOD_EYE_GUILT_RIGHT: path = guilt_right; count = COUNT(guilt_right); break;
    case MOOD_EYE_HALF: path = half; count = COUNT(half); break;
    }
    relative_path(layer, path, count, cx, cy, scale, scale, thickness, color);
}

static void draw_mouth(
    lv_layer_t *layer,
    mood_mouth_glyph_t glyph,
    int cx,
    int cy,
    int scale_x,
    int scale_y,
    lv_color_t color
)
{
    static const point_t smile[] = {{-13, -3}, {-9, 1}, {-5, 4}, {0, 6}, {5, 4}, {9, 1}, {13, -3}};
    static const point_t proud[] = {{-12, -1}, {-6, 2}, {0, 3}, {6, 2}, {12, -1}};
    static const point_t small_smile[] = {{-9, -2}, {-5, 1}, {0, 3}, {5, 1}, {9, -2}};
    static const point_t small_frown[] = {{-9, 3}, {-5, 0}, {0, -2}, {5, 0}, {9, 3}};
    static const point_t frown[] = {{-13, 4}, {-8, 0}, {-3, -3}, {0, -4}, {3, -3}, {8, 0}, {13, 4}};
    static const point_t omega[] = {{-15, -4}, {-13, 2}, {-9, 7}, {-5, 6}, {0, 0}, {5, 6}, {9, 7}, {13, 2}, {15, -4}};
    static const point_t wave[] = {{-14, 1}, {-10, -2}, {-6, 2}, {-2, -2}, {2, 2}, {6, -2}, {10, 2}, {14, -1}};
    static const point_t skew[] = {{-12, 2}, {-6, -2}, {0, -3}, {7, 0}, {13, 5}};
    static const point_t flat[] = {{-11, 0}, {11, 0}};

    const point_t *path = NULL;
    size_t count = 0;
    switch (glyph) {
    case MOOD_MOUTH_NONE:
        return;
    case MOOD_MOUTH_TEETH: {
        int left = cx - 15 * scale_x / 100;
        int right = cx + 15 * scale_x / 100;
        int top = cy - 6 * scale_y / 100;
        int bottom = cy + 6 * scale_y / 100;
        pixel_line(layer, left, top, right, top, 2, color);
        pixel_line(layer, right, top, right, bottom, 2, color);
        pixel_line(layer, right, bottom, left, bottom, 2, color);
        pixel_line(layer, left, bottom, left, top, 2, color);
        pixel_line(layer, left, cy, right, cy, 1, color);
        for (int offset = -7; offset <= 7; offset += 7) {
            int x = cx + offset * scale_x / 100;
            pixel_line(layer, x, top, x, bottom, 1, color);
        }
        return;
    }
    case MOOD_MOUTH_OPEN:
    case MOOD_MOUTH_OPEN_SMILE: {
        int width = (glyph == MOOD_MOUTH_OPEN ? 8 : 13) * scale_x / 100;
        int top = cy - (glyph == MOOD_MOUTH_OPEN ? 8 : 4) * scale_y / 100;
        int bottom = cy + 8 * scale_y / 100;
        point_t outline[] = {{cx - width, top}, {cx + width, top}, {cx + width + 2, cy}, {cx, bottom}, {cx - width - 2, cy}, {cx - width, top}};
        for (size_t index = 1; index < COUNT(outline); ++index) {
            pixel_line(layer, outline[index - 1].x, outline[index - 1].y,
                       outline[index].x, outline[index].y, 2, color);
        }
        return;
    }
    case MOOD_MOUTH_SMILE: path = smile; count = COUNT(smile); break;
    case MOOD_MOUTH_PROUD_SMILE: path = proud; count = COUNT(proud); break;
    case MOOD_MOUTH_SMALL_SMILE: path = small_smile; count = COUNT(small_smile); break;
    case MOOD_MOUTH_SMALL_FROWN: path = small_frown; count = COUNT(small_frown); break;
    case MOOD_MOUTH_FROWN: path = frown; count = COUNT(frown); break;
    case MOOD_MOUTH_OMEGA: path = omega; count = COUNT(omega); break;
    case MOOD_MOUTH_WAVE: path = wave; count = COUNT(wave); break;
    case MOOD_MOUTH_SKEW_FROWN: path = skew; count = COUNT(skew); break;
    case MOOD_MOUTH_FLAT: path = flat; count = COUNT(flat); break;
    }
    relative_path(layer, path, count, cx, cy, scale_x, scale_y, 2, color);
}

static void draw_accent(
    lv_layer_t *layer,
    mood_accent_glyph_t glyph,
    int x,
    int y,
    lv_color_t color
)
{
    switch (glyph) {
    case MOOD_ACCENT_TEAR:
    case MOOD_ACCENT_SWEAT: {
        int height = glyph == MOOD_ACCENT_TEAR ? 6 : 5;
        point_t drop[] = {{x, y - height}, {x - 3, y}, {x, y + height}, {x + 3, y}, {x, y - height}};
        for (size_t index = 1; index < COUNT(drop); ++index) {
            pixel_line(layer, drop[index - 1].x, drop[index - 1].y,
                       drop[index].x, drop[index].y, 2, color);
        }
        break;
    }
    case MOOD_ACCENT_SPARKLE:
        pixel_line(layer, x, y - 5, x, y + 5, 1, color);
        pixel_line(layer, x - 5, y, x + 5, y, 1, color);
        break;
    case MOOD_ACCENT_RISE:
        pixel_line(layer, x - 4, y + 3, x, y - 2, 1, color);
        pixel_line(layer, x, y - 2, x + 4, y + 3, 1, color);
        break;
    case MOOD_ACCENT_EXHALE:
        pixel_line(layer, x, y, x + 5, y - 1, 1, color);
        pixel_line(layer, x + 5, y - 1, x + 10, y, 1, color);
        break;
    case MOOD_ACCENT_STRESS:
        pixel_line(layer, x - 5, y - 5, x, y, 2, color);
        pixel_line(layer, x, y, x - 5, y + 5, 2, color);
        break;
    case MOOD_ACCENT_QUESTION:
        pixel_line(layer, x - 4, y - 5, x, y - 8, 2, color);
        pixel_line(layer, x, y - 8, x + 4, y - 5, 2, color);
        pixel_line(layer, x + 4, y - 5, x + 4, y - 1, 2, color);
        pixel_line(layer, x + 4, y - 1, x, y + 2, 2, color);
        pixel_line(layer, x, y + 2, x, y + 5, 2, color);
        block(layer, x - 1, y + 9, 2, 2, color);
        break;
    case MOOD_ACCENT_NONE:
        break;
    }
}

static void apply_frame(const mood_animation_frame_t *frame)
{
    uint32_t lifted = lift_rgb(current_state.foreground_rgb, frame->color_lift);
    lv_color_t color = lv_color_hex(dim_rgb(lifted, frame->face_opacity));
    lv_canvas_fill_bg(canvas, lv_color_black(), LV_OPA_COVER);
    lv_layer_t layer;
    lv_canvas_init_layer(canvas, &layer);

    int center_x = LOGICAL_WIDTH / 2 + frame->face_x;
    int eye_y = frame->eye_y + frame->face_y;
    draw_eye(&layer, frame->left_eye,
             center_x - frame->eye_spread + frame->eye_shift_x,
             eye_y, frame->eye_scale, color);
    draw_eye(&layer, frame->right_eye,
             center_x + frame->eye_spread + frame->eye_shift_x,
             eye_y, frame->eye_scale, color);
    draw_mouth(&layer, frame->mouth, center_x,
               frame->mouth_y + frame->face_y,
               frame->mouth_scale_x, frame->mouth_scale_y, color);

    if (frame->cheek_opacity > 0) {
        uint8_t opacity = (uint8_t)((uint16_t)frame->cheek_opacity *
                                    frame->face_opacity / 255U);
        lv_color_t cheek = lv_color_hex(dim_rgb(lifted, opacity));
        for (int side = -1; side <= 1; side += 2) {
            int cheek_x = center_x + side * 53;
            for (int offset = -5; offset <= 5; offset += 5) {
                pixel_line(&layer, cheek_x + offset - 2, 69 + frame->face_y,
                           cheek_x + offset + 2, 65 + frame->face_y, 1, cheek);
            }
        }
    }
    draw_accent(&layer, frame->accent,
                frame->accent_x + frame->face_x,
                frame->accent_y + frame->face_y, color);
    lv_canvas_finish_layer(canvas, &layer);
}

void mood_face_init(void)
{
    screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    canvas_buffer = heap_caps_malloc(
        SCREEN_WIDTH * SCREEN_HEIGHT * sizeof(lv_color_t),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT
    );
    if (canvas_buffer == NULL) {
        canvas_buffer = malloc(SCREEN_WIDTH * SCREEN_HEIGHT * sizeof(lv_color_t));
    }
    if (canvas_buffer == NULL) {
        abort();
    }
    canvas = lv_canvas_create(screen);
    lv_canvas_set_buffer(canvas, canvas_buffer, SCREEN_WIDTH, SCREEN_HEIGHT,
                         LV_COLOR_FORMAT_RGB565);
    lv_obj_center(canvas);
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
    mood_animation_frame(current_state.face, current_state.energy,
                         elapsed_ms - animation_started_ms, &frame);
    apply_frame(&frame);
}
