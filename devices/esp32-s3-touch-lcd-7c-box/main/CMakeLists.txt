idf_component_register(
    SRCS "main.c" "mood_protocol.c" "mood_offline.c" "mood_animation.c"
         "mood_face.c" "board_display.c"
    INCLUDE_DIRS "."
    REQUIRES esp_lcd esp_timer usb json
)
