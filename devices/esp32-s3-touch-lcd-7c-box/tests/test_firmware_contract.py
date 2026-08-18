from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_firmware_versions_and_wire_contract_are_pinned() -> None:
    component = (ROOT / "main" / "idf_component.yml").read_text(encoding="utf-8")
    protocol = (ROOT / "main" / "mood_protocol.h").read_text(encoding="utf-8")
    offline = (ROOT / "main" / "mood_offline.c").read_text(encoding="utf-8")

    assert 'idf: "==5.5.3"' in component
    assert '"armi.mood-display.v1"' in protocol
    assert "MOOD_FRAME_MAX_BYTES 512" in protocol
    assert "30LL * 1000 * 1000" in offline
    assert (ROOT / "host_tests" / "test_mood_display.c").is_file()


def test_v1_initializes_only_display_and_usb_serial() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "main").glob("*.c")
    ).lower()

    for forbidden in ("esp_wifi", "esp_netif", "touch_init", "i2s_channel"):
        assert forbidden not in sources
    assert "board_display_init" in sources
    assert "usb_serial_jtag_driver_install" in sources


def test_all_ten_wire_faces_have_firmware_names() -> None:
    protocol = (ROOT / "main" / "mood_protocol.c").read_text(encoding="utf-8")
    for face in (
        "happy",
        "excited",
        "calm",
        "sad",
        "anxious",
        "angry",
        "disgusted",
        "embarrassed",
        "neutral",
        "offline",
    ):
        assert f'"{face}"' in protocol
