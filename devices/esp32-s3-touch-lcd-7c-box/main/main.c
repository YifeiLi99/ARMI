#include <stdio.h>
#include <string.h>

#include "board_display.h"
#include "esp_check.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "mood_face.h"
#include "mood_offline.h"
#include "mood_protocol.h"
#include "usb/usb_serial_jtag.h"

static void send_frame(const char *frame, size_t length)
{
    usb_serial_jtag_write_bytes(frame, length, pdMS_TO_TICKS(1000));
}

void app_main(void)
{
    ESP_ERROR_CHECK(board_display_init());
    mood_face_init();
    const usb_serial_jtag_driver_config_t usb_config = {
        .rx_buffer_size = 1024,
        .tx_buffer_size = 1024,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_config));
    char boot_id[17];
    snprintf(boot_id, sizeof(boot_id), "%08lx%08lx",
             (unsigned long)esp_random(), (unsigned long)esp_random());
    char output[MOOD_FRAME_MAX_BYTES + 1];
    size_t output_length = mood_protocol_hello(output, sizeof(output), boot_id);
    send_frame(output, output_length);

    char input[MOOD_FRAME_MAX_BYTES + 1];
    size_t used = 0;
    mood_offline_state_t offline_state;
    mood_offline_init(&offline_state);
    while (true) {
        int received = usb_serial_jtag_read_bytes(
            input + used, MOOD_FRAME_MAX_BYTES - used, pdMS_TO_TICKS(20)
        );
        if (received > 0) {
            used += (size_t)received;
            char *newline = memchr(input, '\n', used);
            if (newline != NULL) {
                size_t frame_length = (size_t)(newline - input) + 1;
                mood_parse_result_t parsed = mood_protocol_parse(input, frame_length);
                if (parsed.kind == MOOD_PARSE_STATE) {
                    mood_face_apply(&parsed.state);
                    mood_offline_received_state(&offline_state, esp_timer_get_time());
                    output_length = mood_protocol_ack(
                        output, sizeof(output), parsed.state.state_id, "applied"
                    );
                    send_frame(output, output_length);
                } else if (parsed.kind == MOOD_PARSE_PING) {
                    output_length = mood_protocol_pong(
                        output, sizeof(output), parsed.ping_id
                    );
                    send_frame(output, output_length);
                } else if (parsed.state.state_id[0] != '\0') {
                    output_length = mood_protocol_ack(
                        output, sizeof(output), parsed.state.state_id, "invalid_state"
                    );
                    send_frame(output, output_length);
                }
                memmove(input, input + frame_length, used - frame_length);
                used -= frame_length;
            } else if (used == MOOD_FRAME_MAX_BYTES) {
                used = 0;
            }
        }
        int64_t now = esp_timer_get_time();
        if (mood_offline_tick(&offline_state, now)) {
            mood_face_offline();
        }
        mood_face_tick((uint32_t)(now / 1000));
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
