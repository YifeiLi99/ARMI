import re
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


def test_faces_are_rendered_as_unicode_text_assets_and_keep_projected_color() -> None:
    text = (ROOT / "main" / "mood_text.c").read_text(encoding="utf-8")
    catalog = (ROOT / "main" / "mood_text_catalog.inc").read_text(encoding="utf-8")
    asset_data = (ROOT / "main" / "mood_text_assets.bin").read_bytes()
    face = (ROOT / "main" / "mood_face.c").read_text(encoding="utf-8")
    component = (ROOT / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

    entries = re.findall(r'^\{"(.+)", (\d+)U, (\d+)U, (\d+)U\}', catalog, re.MULTILINE)
    assert len(entries) == 22
    assert all(not expression.isascii() for expression, *_ in entries)
    assert max(len(expression) for expression, *_ in entries) >= 12
    expected_offset = 0
    for expression, offset, width, height in entries:
        assert expression
        assert int(offset) == expected_offset
        assert 0 < int(width) <= 720
        assert 0 < int(height) <= 160
        expected_offset += int(width) * int(height)
    assert expected_offset == len(asset_data)
    assert "mood_text_expression" in text
    assert "color_lift" in text
    assert "lift_rgb" in face
    assert "lv_color_black" in face
    assert "LV_COLOR_FORMAT_A8" in face
    assert "lv_image_set_src" in face
    assert "lv_obj_set_style_image_recolor" in face
    assert "lv_label" not in face
    assert "lv_canvas" not in face
    assert '"mood_text.c"' in component
    assert 'EMBED_FILES "mood_text_assets.bin"' in component
    assert not (ROOT / "main" / "mood_animation.c").exists()


def test_generator_and_desktop_preview_use_the_firmware_catalog() -> None:
    catalog = (ROOT / "main" / "mood_text_catalog.inc").read_text(encoding="utf-8")
    expressions = re.findall(r'^\{"(.+)",', catalog, re.MULTILINE)
    generator = (ROOT / "tools" / "generate_kaomoji_assets.py").read_text(
        encoding="utf-8"
    )
    preview = (ROOT.parents[1] / "tools" / "mood_display_preview.py").read_text(
        encoding="utf-8"
    )

    for expression in expressions:
        assert f'"{expression}"' in generator
        assert f'"{expression}"' in preview
    assert "unexpected Noto Sans SC source font digest" in generator
    assert "expression contains unsupported glyphs" in generator
