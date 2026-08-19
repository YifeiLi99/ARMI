from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_firmware_versions_and_wire_contract_are_pinned() -> None:
    component = (ROOT / "main" / "idf_component.yml").read_text(encoding="utf-8")
    protocol = (ROOT / "main" / "mood_protocol.h").read_text(encoding="utf-8")
    offline = (ROOT / "main" / "mood_offline.c").read_text(encoding="utf-8")

    assert 'idf: "==5.5.3"' in component
    assert '"armi.mood-display.v2"' in protocol
    assert "MOOD_FRAME_MAX_BYTES 512" in protocol
    assert "30LL * 1000 * 1000" in offline
    assert "background_rgb == 0x000000U" in (
        ROOT / "main" / "mood_protocol.c"
    ).read_text(encoding="utf-8")
    assert (ROOT / "host_tests" / "test_mood_display.c").is_file()


def test_v1_initializes_only_display_and_usb_serial() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "main").glob("*.c")
    ).lower()

    for forbidden in ("esp_wifi", "esp_netif", "touch_init", "i2s_channel"):
        assert forbidden not in sources
    assert "board_display_init" in sources
    assert "usb_serial_jtag_driver_install" in sources


def test_all_twenty_emotions_and_device_states_have_firmware_names() -> None:
    protocol = (ROOT / "main" / "mood_protocol.c").read_text(encoding="utf-8")
    for face in (
        *(f"face_{index:02d}" for index in range(1, 21)),
        "neutral",
        "offline",
    ):
        assert f'"{face}"' in protocol
    for private_name in ("joy", "sadness", "anger", "shame", "guilt"):
        assert f'"{private_name}"' not in protocol


def test_online_faces_use_expression_specific_frame_animation_and_color() -> None:
    animation = (ROOT / "main" / "mood_animation.c").read_text(encoding="utf-8")
    face = (ROOT / "main" / "mood_face.c").read_text(encoding="utf-8")
    component = (ROOT / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

    for enum_name in (
        "MOOD_FACE_JOY",
        "MOOD_FACE_CONTENTMENT",
        "MOOD_FACE_INTEREST",
        "MOOD_FACE_HOPE",
        "MOOD_FACE_RELIEF",
        "MOOD_FACE_AFFECTION",
        "MOOD_FACE_GRATITUDE",
        "MOOD_FACE_PRIDE",
        "MOOD_FACE_SURPRISE",
        "MOOD_FACE_SADNESS",
        "MOOD_FACE_FEAR",
        "MOOD_FACE_ANXIETY",
        "MOOD_FACE_ANGER",
        "MOOD_FACE_FRUSTRATION",
        "MOOD_FACE_DISGUST",
        "MOOD_FACE_SHAME",
        "MOOD_FACE_GUILT",
        "MOOD_FACE_JEALOUSY",
        "MOOD_FACE_BOREDOM",
        "MOOD_FACE_CONFUSION",
    ):
        assert enum_name in animation
    assert "FRAME_MS 80U" in animation
    assert "color_lift" in animation
    assert "cheek_opacity" in animation
    assert "MOOD_ACCENT_QUESTION" in animation
    assert "lift_rgb" in face
    assert "lv_color_black" in face
    assert "PIXEL_SCALE 4" in face
    assert "lv_canvas_init_layer" in face
    assert '"mood_animation.c"' in component
