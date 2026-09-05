#include "board_display.h"

#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lvgl.h"

static esp_lcd_panel_handle_t panel;
static lv_display_t *display;
static i2c_master_dev_handle_t extension;
static SemaphoreHandle_t frame_finished;

static esp_err_t extension_write(uint8_t reg, uint16_t value)
{
    const uint8_t data[] = {reg, value & 0xffU, value >> 8};
    return i2c_master_transmit(extension, data, sizeof(data), 1000);
}

static esp_err_t display_power_init(void)
{
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0, .sda_io_num = 47, .scl_io_num = 48,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_config, &bus), "board", "I2C bus");
    const i2c_device_config_t device = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = 0x24, .scl_speed_hz = 100000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(bus, &device, &extension),
                        "board", "IO extension");
    // Only LCD reset, backlight and VCOM power are outputs (EXIO0/2/5).
    ESP_RETURN_ON_ERROR(extension_write(0x03, 0), "board", "LCD off");
    ESP_RETURN_ON_ERROR(extension_write(0x02, 0x25), "board", "LCD IO mode");
    ESP_RETURN_ON_ERROR(extension_write(0x03, 0x20), "board", "LCD power");
    vTaskDelay(pdMS_TO_TICKS(100));
    ESP_RETURN_ON_ERROR(extension_write(0x03, 0x21), "board", "LCD reset release");
    vTaskDelay(pdMS_TO_TICKS(100));
    const uint8_t brightness[] = {0x05, 128};
    return i2c_master_transmit(extension, brightness, sizeof(brightness), 1000);
}

static uint32_t tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static bool frame_complete(esp_lcd_panel_handle_t handle,
                           const esp_lcd_rgb_panel_event_data_t *event, void *context)
{
    BaseType_t awakened = pdFALSE;
    xSemaphoreGiveFromISR(frame_finished, &awakened);
    return awakened == pdTRUE;
}

static void flush(lv_display_t *disp, const lv_area_t *area, uint8_t *pixels)
{
    ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1,
                                            area->x2 + 1, area->y2 + 1, pixels));
    // Discard an earlier completion; wait until DMA has switched buffers.
    xSemaphoreTake(frame_finished, 0);
    ESP_ERROR_CHECK(xSemaphoreTake(frame_finished, pdMS_TO_TICKS(1000)) == pdTRUE
                        ? ESP_OK : ESP_ERR_TIMEOUT);
    lv_display_flush_ready(disp);
}

esp_err_t board_display_init(void)
{
    ESP_RETURN_ON_ERROR(display_power_init(), "board", "display power");
    frame_finished = xSemaphoreCreateBinary();
    ESP_RETURN_ON_FALSE(frame_finished != NULL, ESP_ERR_NO_MEM, "board", "frame semaphore");
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
    const esp_lcd_rgb_panel_event_callbacks_t callbacks = {
        .on_frame_buf_complete = frame_complete,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_rgb_panel_register_event_callbacks(panel, &callbacks, NULL),
                        "board", "frame callback");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(panel), "board", "panel init");
    void *first = NULL;
    void *second = NULL;
    ESP_RETURN_ON_ERROR(esp_lcd_rgb_panel_get_frame_buffer(panel, 2, &first, &second),
                        "board", "framebuffer");
    lv_init();
    lv_tick_set_cb(tick_ms);
    display = lv_display_create(800, 480);
    ESP_RETURN_ON_FALSE(display != NULL, ESP_ERR_NO_MEM, "board", "LVGL display");
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(display, flush);
    lv_display_set_buffers(display, second, first, 800 * 480 * 2,
                           LV_DISPLAY_RENDER_MODE_FULL);
    return extension_write(0x03, 0x25);
}
