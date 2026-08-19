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
    left_eye_width: int = 76
    left_eye_height: int = 14
    left_eye_x: int = -120
    left_eye_y: int = -65
    left_eye_rotation: int = 0
    left_eye_curve: int = 0
    right_eye_width: int = 76
    right_eye_height: int = 14
    right_eye_x: int = 120
    right_eye_y: int = -65
    right_eye_rotation: int = 0
    right_eye_curve: int = 0
    mouth_width: int = 72
    mouth_height: int = 13
    mouth_x: int = 0
    mouth_y: int = 82
    mouth_curve: int = 0
    cheek_opacity: int = 0
    cheek_y: int = 34
    accent_visible: bool = False
    accent_width: int = 0
    accent_height: int = 0
    accent_x: int = 0
    accent_y: int = 0
    color_lift: int = 0
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
    target.color_lift = triangle(frame, 50, 2 + energy // 16)
    target.face_opacity = min(255, 96 + elapsed_ms * 159 // 320)

    if face == "happy":
        target.left_eye_width = target.right_eye_width = 92 + breath
        target.left_eye_height = target.right_eye_height = 34 + breath
        target.left_eye_curve = target.right_eye_curve = -1
        target.mouth_width = 86 + breath * 2
        target.mouth_height = 42 + breath
        target.mouth_y = 76 - breath
        target.mouth_curve = 1
        target.cheek_opacity = 55 + triangle(frame, 50, 40)
    elif face == "excited":
        bounce = triangle(frame, 18, drive * 2)
        target.left_eye_width = target.right_eye_width = 98 + bounce
        target.left_eye_height = target.right_eye_height = 16
        target.left_eye_rotation = 180
        target.right_eye_rotation = -180
        target.left_eye_y = target.right_eye_y = -65 - bounce
        target.mouth_width = 74 + bounce * 2
        target.mouth_height = 68 + bounce
        target.mouth_y = 78 - bounce
        target.mouth_curve = 2
        target.cheek_opacity = 70 + triangle(frame, 18, 50)
        target.color_lift = 5 + triangle(frame, 18, 4 + energy // 10)
    elif face == "calm":
        target.left_eye_width = target.right_eye_width = 82 + breath
        target.left_eye_height = target.right_eye_height = 11
        target.mouth_width = 64 + breath * 2
        target.mouth_height = 30
        target.mouth_y = 80 + breath // 2
        target.mouth_curve = 1
        target.color_lift = triangle(frame, 75, 5)
    elif face == "sad":
        drift = triangle(frame, 70, drive)
        target.left_eye_width = target.right_eye_width = 76
        target.left_eye_height = target.right_eye_height = 13
        target.left_eye_y = -61 + drift
        target.right_eye_y = -57 + drift
        target.left_eye_rotation = -140
        target.right_eye_rotation = 140
        target.mouth_width = 72 - drift
        target.mouth_height = 34
        target.mouth_y = 94 + drift
        target.mouth_curve = -1
        target.accent_visible = True
        target.accent_width = 13
        target.accent_height = 24 + triangle(frame, 35, 20)
        target.accent_x = 181
        target.accent_y = -17 + triangle(frame, 35, 36)
        target.color_lift = 0
    elif face == "anxious":
        jitter = signed_swing(frame, 8, drive)
        target.left_eye_width = target.right_eye_width = 44
        target.left_eye_height = target.right_eye_height = 58 + breath
        target.left_eye_curve = target.right_eye_curve = 2
        target.left_eye_x += jitter
        target.right_eye_x += jitter
        target.mouth_width = 74 + triangle(frame, 10, drive * 2)
        target.mouth_height = 12 + triangle(frame, 10, drive)
        target.accent_visible = True
        target.accent_width = 16
        target.accent_height = 26
        target.accent_x = 214 + jitter
        target.accent_y = -92 + triangle(frame, 16, 18)
        target.color_lift = triangle(frame, 10, 3 + energy // 12)
    elif face == "angry":
        pulse = triangle(frame, 20, drive * 2)
        target.left_eye_width = target.right_eye_width = 96 + pulse
        target.left_eye_height = target.right_eye_height = 15
        target.left_eye_y = target.right_eye_y = -58 + pulse // 3
        target.left_eye_rotation = 210
        target.right_eye_rotation = -210
        target.mouth_width = 88 + pulse
        target.mouth_height = 15 + pulse // 3
        target.mouth_y = 91 - pulse // 3
        target.color_lift = triangle(frame, 20, 4 + energy // 10)
    elif face == "disgusted":
        recoil = triangle(frame, 34, drive * 2)
        target.left_eye_width = 72 + recoil
        target.left_eye_height = 32
        target.left_eye_curve = -1
        target.right_eye_height = 12
        target.right_eye_width = 70 - recoil
        target.right_eye_rotation = -120
        target.mouth_width = 70 - recoil
        target.mouth_height = 28
        target.mouth_x = 25 + recoil
        target.mouth_y = 88 + recoil // 2
        target.mouth_curve = -1
        target.color_lift = triangle(frame, 34, 6)
    elif face == "embarrassed":
        hide = triangle(frame, 42, drive * 2)
        target.left_eye_width = target.right_eye_width = 72
        target.left_eye_height = target.right_eye_height = 30 - hide // 3
        target.left_eye_curve = target.right_eye_curve = -1
        target.left_eye_y = target.right_eye_y = -58 + hide
        target.mouth_width = 54 + breath
        target.mouth_height = 12
        target.mouth_y = 90 + hide // 2
        target.cheek_opacity = 120 + triangle(frame, 20, 85)
        target.color_lift = triangle(frame, 42, 8)
    elif face == "offline":
        target.left_eye_height = target.right_eye_height = 8
        target.mouth_width = 64
        target.mouth_height = 8
        target.color_lift = 0
        target.face_opacity = 180
    else:
        target.left_eye_width = target.right_eye_width = 22 + breath // 2
        target.left_eye_height = target.right_eye_height = 26 + breath // 2
        target.mouth_y += breath // 2
        glance = signed_swing(frame, 80, 3)
        target.left_eye_x += glance
        target.right_eye_x += glance
        target.color_lift = triangle(frame, 80, 3)

    if face not in {"offline", "calm"}:
        period = 31 if face == "anxious" else 47 if face == "excited" else 59
        closed_frames = 2 if energy >= 60 else 1
        if (frame + period // 2) % period < closed_frames:
            target.left_eye_height = target.right_eye_height = 8
            target.left_eye_curve = target.right_eye_curve = 0
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

        self.auto_play = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="自动轮播", variable=self.auto_play).grid(row=0, column=5)

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

        self.status = ttk.Label(root, padding=(14, 10, 14, 14), anchor="center")
        self.status.grid(row=2, column=0, sticky="ew")
        self._tick()

    def _select_face(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.current_face = FACE_BY_LABEL[self.face_label.get()].key
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at

    def _draw_oval(
        self, width: int, height: int, x: int, y: int, color: str, *, outline: bool = False
    ) -> None:
        center_x = SCREEN_WIDTH // 2 + x
        center_y = SCREEN_HEIGHT // 2 + y
        self.canvas.create_oval(
            center_x - width / 2,
            center_y - height / 2,
            center_x + width / 2,
            center_y + height / 2,
            fill="" if outline else color,
            outline=color if outline else "",
            width=10 if outline else 1,
        )

    def _draw_eye(
        self,
        width: int,
        height: int,
        x: int,
        y: int,
        rotation: int,
        curve: int,
        color: str,
    ) -> None:
        center_x = SCREEN_WIDTH // 2 + x
        center_y = SCREEN_HEIGHT // 2 + y
        stroke = max(8, min(14, height))
        if curve == 2:
            self._draw_oval(width, height, x, y, color, outline=True)
            return
        if curve:
            start = 0 if curve < 0 else 180
            self.canvas.create_arc(
                center_x - width / 2,
                center_y - height / 2,
                center_x + width / 2,
                center_y + height / 2,
                start=start,
                extent=180,
                style=tk.ARC,
                outline=color,
                width=stroke,
            )
            return
        if width <= 30 and height >= 20:
            self._draw_oval(width, height, x, y, color)
            return
        angle = math.radians(rotation / 10)
        delta_x = math.cos(angle) * width / 2
        delta_y = math.sin(angle) * width / 2
        self.canvas.create_line(
            center_x - delta_x,
            center_y - delta_y,
            center_x + delta_x,
            center_y + delta_y,
            fill=color,
            width=stroke,
            capstyle=tk.ROUND,
        )

    def _draw_mouth(self, frame: AnimationFrame, color: str) -> None:
        center_x = SCREEN_WIDTH // 2 + frame.mouth_x
        center_y = SCREEN_HEIGHT // 2 + frame.mouth_y
        if frame.mouth_curve == 2:
            self._draw_oval(
                frame.mouth_width,
                frame.mouth_height,
                frame.mouth_x,
                frame.mouth_y,
                color,
                outline=True,
            )
        elif frame.mouth_curve:
            self.canvas.create_arc(
                center_x - frame.mouth_width / 2,
                center_y - frame.mouth_height / 2,
                center_x + frame.mouth_width / 2,
                center_y + frame.mouth_height / 2,
                start=180 if frame.mouth_curve > 0 else 0,
                extent=180,
                style=tk.ARC,
                outline=color,
                width=11,
            )
        else:
            self.canvas.create_line(
                center_x - frame.mouth_width / 2,
                center_y,
                center_x + frame.mouth_width / 2,
                center_y,
                fill=color,
                width=max(8, frame.mouth_height),
                capstyle=tk.ROUND,
            )

    def _draw(self, frame: AnimationFrame, expression_color: str) -> None:
        face_color = blend_color("#000000", expression_color, frame.face_opacity)
        self.canvas.configure(background="#000000")
        self.canvas.delete("all")
        self._draw_eye(
            frame.left_eye_width,
            frame.left_eye_height,
            frame.left_eye_x,
            frame.left_eye_y,
            frame.left_eye_rotation,
            frame.left_eye_curve,
            face_color,
        )
        self._draw_eye(
            frame.right_eye_width,
            frame.right_eye_height,
            frame.right_eye_x,
            frame.right_eye_y,
            frame.right_eye_rotation,
            frame.right_eye_curve,
            face_color,
        )
        self._draw_mouth(frame, face_color)
        if frame.cheek_opacity:
            cheek_color = blend_color(
                "#000000",
                expression_color,
                frame.cheek_opacity * frame.face_opacity // 255,
            )
            for center in (SCREEN_WIDTH // 2 - 220, SCREEN_WIDTH // 2 + 220):
                y = SCREEN_HEIGHT // 2 + frame.cheek_y
                for offset in (-18, 0, 18):
                    self.canvas.create_line(
                        center + offset - 8,
                        y + 10,
                        center + offset + 8,
                        y - 10,
                        fill=cheek_color,
                        width=6,
                        capstyle=tk.ROUND,
                    )
        if frame.accent_visible:
            accent_color = blend_color("#000000", expression_color, frame.face_opacity)
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
        expression_color = lift_color(spec.color, frame.color_lift)
        self._draw(frame, expression_color)
        self.status.configure(text=f"{spec.label}    {spec.motion}    {spec.color}    energy {energy}")
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
                assert 0 <= frame.color_lift <= 100
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
