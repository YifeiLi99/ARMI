"""ARMI ESP32 文字心情屏的独立桌面预览器。"""

from __future__ import annotations

import argparse
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
FRAME_MS = 80


@dataclass(frozen=True)
class FaceSpec:
    key: str
    label: str
    color: str
    expression: str


FACES = (
    FaceSpec("joy", "喜悦", "#FFD166", "(^o^)"),
    FaceSpec("contentment", "满足", "#6BCB77", "(-v-)"),
    FaceSpec("interest", "兴趣", "#4CC9F0", "(o.o)"),
    FaceSpec("hope", "希望", "#72DDF7", "(^_^)"),
    FaceSpec("relief", "如释重负", "#52B69A", "(-.-)"),
    FaceSpec("affection", "喜爱", "#FF7AA2", "(<3_<3)"),
    FaceSpec("gratitude", "感激", "#F4A261", "(^.^)"),
    FaceSpec("pride", "自豪", "#C77DFF", "(-w-)"),
    FaceSpec("surprise", "惊讶", "#FF9F1C", "(O_O)"),
    FaceSpec("sadness", "悲伤", "#4E79A7", "(T_T)"),
    FaceSpec("fear", "恐惧", "#6C63A8", "(O~O)"),
    FaceSpec("anxiety", "焦虑", "#8F77B5", "(@_@)"),
    FaceSpec("anger", "愤怒", "#E15759", "(>_<)"),
    FaceSpec("frustration", "挫败", "#F05D5E", "(>~<)"),
    FaceSpec("disgust", "厌恶", "#7A9E3A", "(-_-;)"),
    FaceSpec("shame", "羞耻", "#B565A7", "(//_//)"),
    FaceSpec("guilt", "内疚", "#D7799F", "(;_;)"),
    FaceSpec("jealousy", "嫉妒", "#83A14A", "(<_<)"),
    FaceSpec("boredom", "无聊", "#7D8597", "(-_-)"),
    FaceSpec("confusion", "困惑", "#5DADE2", "(o_O)?"),
    FaceSpec("neutral", "中性", "#667085", "(._.)"),
    FaceSpec("offline", "离线", "#3A3F47", "(- -)"),
)
FACE_BY_LABEL = {face.label: face for face in FACES}
FACE_BY_KEY = {face.key: face for face in FACES}
ONLINE_FACE_KEYS = tuple(face.key for face in FACES if face.key != "offline")


def triangle(frame: int, period: int, amplitude: int) -> int:
    position = frame % period
    half = period // 2
    value = position if position <= half else period - position
    return value * amplitude // half


def lift_color(hex_color: str, percent: int) -> str:
    rgb = tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5))
    lifted = tuple(value + (255 - value) * percent // 100 for value in rgb)
    return "#" + "".join(f"{value:02X}" for value in lifted)


def blend_black(foreground: str, opacity: int) -> str:
    rgb = tuple(int(foreground[index : index + 2], 16) for index in (1, 3, 5))
    dimmed = tuple(value * opacity // 255 for value in rgb)
    return "#" + "".join(f"{value:02X}" for value in dimmed)


def expression_color(face: FaceSpec, energy: int, elapsed_ms: int) -> str:
    if face.key == "offline":
        return blend_black(face.color, 180)
    frame = elapsed_ms // FRAME_MS
    lift = triangle(frame, 50, 2 + energy // 18)
    opacity = min(255, 96 + elapsed_ms * 159 // 320)
    return blend_black(lift_color(face.color, lift), opacity)


class MoodDisplayPreview:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at
        self.current_face = "anger"
        root.title("ARMI 文字颜表情预览")
        root.configure(background="#17191E")
        root.resizable(False, False)

        controls = ttk.Frame(root, padding=(14, 12, 14, 10))
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="表情").grid(row=0, column=0, padx=(0, 6))
        self.face_label = tk.StringVar(value=FACE_BY_KEY[self.current_face].label)
        face_picker = ttk.Combobox(
            controls,
            textvariable=self.face_label,
            values=tuple(face.label for face in FACES),
            width=13,
            state="readonly",
        )
        face_picker.grid(row=0, column=1, padx=(0, 18))
        face_picker.bind("<<ComboboxSelected>>", self._select_face)
        ttk.Label(controls, text="活跃度").grid(row=0, column=2, padx=(0, 6))
        self.energy = tk.IntVar(value=70)
        ttk.Scale(controls, from_=0, to=100, variable=self.energy, length=220).grid(
            row=0, column=3
        )
        self.energy_text = ttk.Label(controls, text="70", width=4)
        self.energy_text.grid(row=0, column=4, padx=(4, 16))
        self.auto_play = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="自动轮播", variable=self.auto_play).grid(
            row=0, column=5
        )

        bezel = tk.Frame(root, background="#252931", padx=14, pady=14)
        bezel.grid(row=1, column=0, padx=14)
        self.canvas = tk.Canvas(
            bezel,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            highlightthickness=0,
            background="#000000",
        )
        self.canvas.pack()
        self.expression = self.canvas.create_text(
            SCREEN_WIDTH // 2,
            SCREEN_HEIGHT // 2,
            text="",
            font=("Montserrat", 96),
            anchor="center",
        )
        self.status = ttk.Label(root, padding=(14, 10, 14, 14), anchor="center")
        self.status.grid(row=2, column=0, sticky="ew")
        self._tick()

    def _select_face(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.current_face = FACE_BY_LABEL[self.face_label.get()].key
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at

    def _tick(self) -> None:
        now = time.monotonic()
        if self.auto_play.get() and now - self.last_auto_change >= 2.6:
            index = (
                (ONLINE_FACE_KEYS.index(self.current_face) + 1) % len(ONLINE_FACE_KEYS)
                if self.current_face in ONLINE_FACE_KEYS
                else 0
            )
            self.current_face = ONLINE_FACE_KEYS[index]
            self.face_label.set(FACE_BY_KEY[self.current_face].label)
            self.started_at = now
            self.last_auto_change = now
        energy = max(0, min(100, int(round(self.energy.get() / 10) * 10)))
        self.energy_text.configure(text=str(energy))
        elapsed_ms = max(0, int((now - self.started_at) * 1000))
        spec = FACE_BY_KEY[self.current_face]
        self.canvas.itemconfigure(
            self.expression,
            text=spec.expression,
            fill=expression_color(spec, energy, elapsed_ms),
        )
        self.status.configure(
            text=f"{spec.label}    {spec.expression}    {spec.color}    energy {energy}"
        )
        self.root.after(FRAME_MS, self._tick)


def smoke_test() -> None:
    assert len(FACES[:20]) == 20
    assert len({face.expression for face in FACES}) == len(FACES)
    assert all(
        face.expression.isascii() and face.expression.isprintable() for face in FACES
    )
    for face in FACES:
        for energy in (0, 50, 100):
            for elapsed_ms in (0, 80, 320, 4_000):
                color = expression_color(face, energy, elapsed_ms)
                assert len(color) == 7 and color.startswith("#")
    assert expression_color(FACE_BY_KEY["offline"], 0, 0) == expression_color(
        FACE_BY_KEY["offline"], 100, 4_000
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-test", action="store_true", help="只验证文字映射且不打开窗口"
    )
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
        print("mood display preview: ok")
        return
    root = tk.Tk()
    MoodDisplayPreview(root)
    root.mainloop()


if __name__ == "__main__":
    main()
