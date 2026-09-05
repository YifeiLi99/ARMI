idf_component_register(
    SRCS "main.c" "mood_protocol.c" "mood_offline.c" "mood_text.c"
         "mood_face.c" "board_display.c"
    INCLUDE_DIRS "."
    REQUIRES esp_lcd esp_timer esp_driver_usb_serial_jtag esp_driver_i2c json
    EMBED_FILES "mood_text_assets.bin"
)
