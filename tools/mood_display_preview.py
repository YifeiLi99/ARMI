"""ARMI ESP32 心情屏的独立桌面预览器。"""

from __future__ import annotations

import argparse
import math
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
    motion: str


FACES = (
    FaceSpec("happy", "开心", "#F6C85F", "呼吸微笑 · 腮红渐变 · 自然眨眼"),
    FaceSpec("excited", "兴奋", "#F28E2B", "眼睛与嘴弹跳 · 背景脉冲 · 快速眨眼"),
    FaceSpec("calm", "平静", "#4EAAA5", "闭眼慢呼吸 · 柔和背景起伏"),
    FaceSpec("sad", "难过", "#4E79A7", "垂眼 · 嘴角下弯 · 泪滴滑落"),
    FaceSpec("anxious", "焦虑", "#8F77B5", "眼神抖动 · 嘴部颤动 · 汗滴移动"),
    FaceSpec("angry", "生气", "#E15759", "压低眼睛 · 嘴部蓄力脉冲"),
    FaceSpec("disgusted", "嫌弃", "#7A9E3A", "大小眼 · 嘴角偏移回缩"),
    FaceSpec("embarrassed", "害羞 / 内疚", "#D7799F", "低头缩眼 · 腮红加深"),
    FaceSpec("neutral", "中性", "#667085", "轻微呼吸 · 视线缓慢游移"),
    FaceSpec("offline", "离线", "#3A3F47", "灰色闭眼脸 · 保持静止"),
)
FACE_BY_LABEL = {face.label: face for face in FACES}
FACE_BY_KEY = {face.key: face for face in FACES}
ONLINE_FACE_KEYS = tuple(face.key for face in FACES if face.key != "offline")


@dataclass
class AnimationFrame:
    left_eye_width: int = 92
    left_eye_height: int = 54
    left_eye_x: int = -145
    left_eye_y: int = -65
    right_eye_width: int = 92
    right_eye_height: int = 54
    right_eye_x: int = 145
    right_eye_y: int = -65
    pupil_size: int = 22
    pupils_visible: bool = True
    pupil_x: int = 0
    pupil_y: int = 0
    mouth_width: int = 180
    mouth_height: int = 18
    mouth_x: int = 0
    mouth_y: int = 105
    mouth_curve: int = 0
    cheek_opacity: int = 0
    cheek_y: int = 34
    accent_visible: bool = False
    accent_width: int = 0
    accent_height: int = 0
    accent_x: int = 0
    accent_y: int = 0
    background_lift: int = 0
    face_opacity: int = 255


def triangle(frame: int, period: int, amplitude: int) -> int:
    position = frame % period
    half = period // 2
    value = position if position <= half else period - position
    return value * amplitude // half


def signed_swing(frame: int, period: int, amplitude: int) -> int:
    return triangle(frame, period, amplitude * 2) - amplitude


def animation_frame(face: str, energy: int, elapsed_ms: int) -> AnimationFrame:
    """按固件 mood_animation.c 的确定性规则生成一帧。"""
    target = AnimationFrame()
    frame = elapsed_ms // FRAME_MS
    drive = 2 + energy // 20
    breath = triangle(frame, 50, drive)
    target.background_lift = triangle(frame, 50, 2 + energy // 16)
    target.face_opacity = min(255, 96 + elapsed_ms * 159 // 320)

    if face == "happy":
        target.left_eye_height = target.right_eye_height = 44 + breath
        target.mouth_width = 230 + breath * 2
        target.mouth_height = 60 + breath
        target.mouth_y = 98 - breath
        target.mouth_curve = 1
        target.cheek_opacity = 75 + triangle(frame, 50, 45)
    elif face == "excited":
        bounce = triangle(frame, 18, drive * 2)
        target.left_eye_width = target.right_eye_width = 110 + bounce
        target.left_eye_height = target.right_eye_height = 70 + bounce
        target.left_eye_y = target.right_eye_y = -65 - bounce // 2
        target.pupil_size = 27 + bounce // 2
        target.mouth_width = 260 + bounce * 2
        target.mouth_height = 78 + bounce
        target.mouth_y = 94 - bounce
        target.mouth_curve = 1
        target.cheek_opacity = 90 + triangle(frame, 18, 55)
        target.background_lift = 5 + triangle(frame, 18, 4 + energy // 10)
    elif face == "calm":
        target.left_eye_width = target.right_eye_width = 100 + breath
        target.left_eye_height = target.right_eye_height = 12
        target.pupils_visible = False
        target.mouth_width = 170 + breath * 2
        target.mouth_height = 12
        target.mouth_y = 104 + breath // 2
        target.background_lift = triangle(frame, 75, 5)
    elif face == "sad":
        drift = triangle(frame, 70, drive)
        target.left_eye_width = target.right_eye_width = 72
        target.left_eye_height = target.right_eye_height = 42 - drift // 2
        target.left_eye_y = -61 + drift
        target.right_eye_y = -57 + drift
        target.pupil_y = 7
        target.mouth_width = 180 - drift * 2
        target.mouth_height = 42
        target.mouth_y = 125 + drift
        target.mouth_curve = -1
        target.accent_visible = True
        target.accent_width = 13
        target.accent_height = 24 + triangle(frame, 35, 20)
        target.accent_x = 181
        target.accent_y = -17 + triangle(frame, 35, 36)
        target.background_lift = 0
    elif face == "anxious":
        jitter = signed_swing(frame, 8, drive)
        target.left_eye_width = target.right_eye_width = 64
        target.left_eye_height = target.right_eye_height = 76 + breath
        target.left_eye_x += jitter
        target.right_eye_x += jitter
        target.pupil_x = -jitter * 2
        target.mouth_width = 116 + triangle(frame, 10, drive * 3)
        target.mouth_height = 18 + triangle(frame, 10, drive)
        target.accent_visible = True
        target.accent_width = 16
        target.accent_height = 26
        target.accent_x = 214 + jitter
        target.accent_y = -92 + triangle(frame, 16, 18)
        target.background_lift = triangle(frame, 10, 3 + energy // 12)
    elif face == "angry":
        pulse = triangle(frame, 20, drive * 2)
        target.left_eye_width = target.right_eye_width = 110 + pulse
        target.left_eye_height = target.right_eye_height = 34 - pulse // 3
        target.left_eye_y = target.right_eye_y = -58 + pulse // 3
        target.pupil_y = 5
        target.mouth_width = 210 + pulse * 2
        target.mouth_height = 25 + pulse // 2
        target.mouth_y = 112 - pulse // 2
        target.background_lift = triangle(frame, 20, 4 + energy // 10)
    elif face == "disgusted":
        recoil = triangle(frame, 34, drive * 2)
        target.left_eye_height = 52 + recoil
        target.right_eye_height = 24
        target.right_eye_width = 76 - recoil
        target.pupil_x = 6
        target.mouth_width = 150 - recoil * 2
        target.mouth_height = 30
        target.mouth_x = 35 + recoil
        target.mouth_y = 108 + recoil // 2
        target.mouth_curve = -1
        target.background_lift = triangle(frame, 34, 6)
    elif face == "embarrassed":
        hide = triangle(frame, 42, drive * 2)
        target.left_eye_width = target.right_eye_width = 70
        target.left_eye_height = target.right_eye_height = 42 - hide // 2
        target.left_eye_y = target.right_eye_y = -58 + hide
        target.pupil_y = 6
        target.mouth_width = 110 + breath
        target.mouth_height = 15
        target.mouth_y = 112 + hide // 2
        target.cheek_opacity = 120 + triangle(frame, 20, 85)
        target.background_lift = triangle(frame, 42, 8)
    elif face == "offline":
        target.left_eye_height = target.right_eye_height = 8
        target.pupils_visible = False
        target.mouth_width = 150
        target.mouth_height = 8
        target.background_lift = 0
        target.face_opacity = 180
    else:
        target.left_eye_height += breath // 2
        target.right_eye_height += breath // 2
        target.mouth_y += breath // 2
        target.pupil_x = signed_swing(frame, 80, 3)
        target.background_lift = triangle(frame, 80, 3)

    if face not in {"offline", "calm"}:
        period = 31 if face == "anxious" else 47 if face == "excited" else 59
        closed_frames = 2 if energy >= 60 else 1
        if (frame + period // 2) % period < closed_frames:
            target.left_eye_height = target.right_eye_height = 8
            target.pupils_visible = False
    return target


def lift_color(hex_color: str, percent: int) -> str:
    rgb = tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5))
    lifted = tuple(value + (255 - value) * percent // 100 for value in rgb)
    return "#" + "".join(f"{value:02X}" for value in lifted)


def blend_color(background: str, foreground: str, opacity: int) -> str:
    bg = tuple(int(background[index : index + 2], 16) for index in (1, 3, 5))
    fg = tuple(int(foreground[index : index + 2], 16) for index in (1, 3, 5))
    mixed = tuple((back * (255 - opacity) + front * opacity) // 255 for back, front in zip(bg, fg, strict=True))
    return "#" + "".join(f"{value:02X}" for value in mixed)


class MoodDisplayPreview:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at
        self.current_face = "happy"

        root.title("ARMI 心情屏预览")
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
        self.energy = tk.IntVar(value=60)
        ttk.Scale(controls, from_=0, to=100, variable=self.energy, length=220).grid(row=0, column=3)
        self.energy_text = ttk.Label(controls, text="60", width=4)
        self.energy_text.grid(row=0, column=4, padx=(4, 16))

        self.color_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="彩色", variable=self.color_enabled).grid(row=0, column=5, padx=(0, 12))
        self.auto_play = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="自动轮播", variable=self.auto_play).grid(row=0, column=6)

        bezel = tk.Frame(root, background="#252931", padx=14, pady=14)
        bezel.grid(row=1, column=0, padx=14)
        self.canvas = tk.Canvas(
            bezel,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            highlightthickness=0,
            background=FACE_BY_KEY[self.current_face].color,
        )
        self.canvas.pack()

        self.status = ttk.Label(root, padding=(14, 10, 14, 14), anchor="center")
        self.status.grid(row=2, column=0, sticky="ew")
        self._tick()

    def _select_face(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.current_face = FACE_BY_LABEL[self.face_label.get()].key
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at

    def _draw_oval(self, width: int, height: int, x: int, y: int, color: str) -> None:
        center_x = SCREEN_WIDTH // 2 + x
        center_y = SCREEN_HEIGHT // 2 + y
        self.canvas.create_oval(
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
            fill=color,
            outline="",
        )

    def _draw(self, frame: AnimationFrame, background: str) -> None:
        face_color = blend_color(background, "#FFFFFF", frame.face_opacity)
        self.canvas.configure(background=background)
        self.canvas.delete("all")
        self._draw_oval(frame.left_eye_width, frame.left_eye_height, frame.left_eye_x, frame.left_eye_y, face_color)
        self._draw_oval(frame.right_eye_width, frame.right_eye_height, frame.right_eye_x, frame.right_eye_y, face_color)
        if frame.pupils_visible:
            self._draw_oval(frame.pupil_size, frame.pupil_size, frame.left_eye_x + frame.pupil_x, frame.left_eye_y + frame.pupil_y, background)
            self._draw_oval(frame.pupil_size, frame.pupil_size, frame.right_eye_x + frame.pupil_x, frame.right_eye_y + frame.pupil_y, background)
        self._draw_oval(frame.mouth_width, frame.mouth_height, frame.mouth_x, frame.mouth_y, face_color)
        if frame.mouth_curve:
            inset = frame.mouth_height // 3
            cutout_y = frame.mouth_y + (-inset if frame.mouth_curve > 0 else inset)
            self._draw_oval(frame.mouth_width - 22, max(1, frame.mouth_height - 14), frame.mouth_x, cutout_y, background)
        if frame.cheek_opacity:
            cheek_color = blend_color(background, "#FFC1D6", frame.cheek_opacity * frame.face_opacity // 255)
            self._draw_oval(78, 30, -225, frame.cheek_y, cheek_color)
            self._draw_oval(78, 30, 225, frame.cheek_y, cheek_color)
        if frame.accent_visible:
            accent_color = blend_color(background, "#BFE8FF", frame.face_opacity)
            self._draw_oval(frame.accent_width, frame.accent_height, frame.accent_x, frame.accent_y, accent_color)

    def _tick(self) -> None:
        now = time.monotonic()
        if self.auto_play.get() and now - self.last_auto_change >= 2.6:
            index = (ONLINE_FACE_KEYS.index(self.current_face) + 1) % len(ONLINE_FACE_KEYS) if self.current_face in ONLINE_FACE_KEYS else 0
            self.current_face = ONLINE_FACE_KEYS[index]
            self.face_label.set(FACE_BY_KEY[self.current_face].label)
            self.started_at = now
            self.last_auto_change = now

        energy = int(round(self.energy.get() / 10) * 10)
        energy = max(0, min(100, energy))
        self.energy_text.configure(text=str(energy))
        elapsed_ms = max(0, math.floor((now - self.started_at) * 1000))
        frame = animation_frame(self.current_face, energy, elapsed_ms)
        spec = FACE_BY_KEY[self.current_face]
        base_color = spec.color if self.color_enabled.get() else "#111111"
        background = lift_color(base_color, frame.background_lift)
        self._draw(frame, background)
        self.status.configure(text=f"{spec.label}    {spec.motion}    {base_color}    energy {energy}")
        self.root.after(FRAME_MS, self._tick)


def smoke_test() -> None:
    for face in FACE_BY_KEY:
        for energy in (0, 50, 100):
            for elapsed_ms in (0, 80, 320, 4_000):
                frame = animation_frame(face, energy, elapsed_ms)
                assert frame.left_eye_width > 0
                assert frame.right_eye_width > 0
                assert frame.mouth_width > 0
                assert 0 <= frame.face_opacity <= 255
                assert 0 <= frame.background_lift <= 100
    assert lift_color("#000000", 100) == "#FFFFFF"
    assert blend_color("#000000", "#FFFFFF", 255) == "#FFFFFF"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="只验证动画计算且不打开窗口")
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
