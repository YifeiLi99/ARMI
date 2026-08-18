#include "board_display.h"

#include "esp_check.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "lvgl.h"

static esp_lcd_panel_handle_t panel;
static lv_display_t *display;

static void flush(lv_display_t *disp, const lv_area_t *area, uint8_t *pixels)
{
    esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1, area->x2 + 1,
                              area->y2 + 1, pixels);
    lv_display_flush_ready(disp);
}

esp_err_t board_display_init(void)
{
    const esp_lcd_rgb_panel_config_t config = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = 16 * 1000 * 1000,
            .h_res = 800, .v_res = 480,
            .hsync_pulse_width = 4, .hsync_back_porch = 8, .hsync_front_porch = 8,
            .vsync_pulse_width = 4, .vsync_back_porch = 8, .vsync_front_porch = 8,
            .flags.pclk_active_neg = 1,
        },
        .data_width = 16, .bits_per_pixel = 16, .num_fbs = 2,
        .bounce_buffer_size_px = 8000,
        .hsync_gpio_num = 46, .vsync_gpio_num = 3, .de_gpio_num = 5,
        .pclk_gpio_num = 7, .disp_gpio_num = -1,
        .data_gpio_nums = {14, 38, 18, 17, 10, 39, 0, 45, 9, 8, 21, 1, 2, 42, 41, 40},
        .flags.fb_in_psram = 1,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_rgb_panel(&config, &panel), "board", "panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(panel), "board", "panel init");
    void *first = NULL;
    void *second = NULL;
    ESP_RETURN_ON_ERROR(esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &first, &second),
                        "board", "framebuffer");
    lv_init();
    display = lv_display_create(800, 480);
    lv_display_set_flush_cb(display, flush);
    lv_display_set_buffers(display, first, second, 800 * 480 * 2,
                           LV_DISPLAY_RENDER_MODE_FULL);
    return ESP_OK;
}
