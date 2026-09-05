#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

esp_err_t board_display_init(void);
esp_err_t board_display_brightness(uint8_t brightness);
esp_err_t board_display_touch(bool *pressed);
