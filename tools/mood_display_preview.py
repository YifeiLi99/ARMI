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
LOGICAL_WIDTH = 200
LOGICAL_HEIGHT = 120
PIXEL_SCALE = 4
FRAME_MS = 80


@dataclass(frozen=True)
class FaceSpec:
    key: str
    label: str
    color: str
    sketch: str
    motion: str


FACES = (
    FaceSpec("joy", "喜悦", "#FFD166", "⌒ ▽ ⌒", "明快弹跳 · 暖光增强"),
    FaceSpec("contentment", "满足", "#6BCB77", "─ ᴗ ─", "闭眼慢呼吸"),
    FaceSpec("interest", "兴趣", "#4CC9F0", "• ◡ •", "聚焦 · 轻微前倾"),
    FaceSpec("hope", "希望", "#72DDF7", "◜ ᴗ ◝", "缓慢抬眼 · 向上浮动"),
    FaceSpec("relief", "如释重负", "#52B69A", "˘ ◡ ˘", "先收紧再舒展 · 呼气点"),
    FaceSpec("affection", "喜爱", "#FF7AA2", "♡ ᴗ ♡", "心形眼轻微搏动"),
    FaceSpec("gratitude", "感激", "#F4A261", "⌒ ◡ ⌒", "柔和低头 · 暖光扩散"),
    FaceSpec("pride", "自豪", "#C77DFF", "￣ ︶ ￣", "稳定抬起 · 微微上扬"),
    FaceSpec("surprise", "惊讶", "#FF9F1C", "○ 口 ○", "瞬间放大 · 短促震动"),
    FaceSpec("sadness", "悲伤", "#4E79A7", "╥ ︿ ╥", "垂眼 · 泪滴滑落"),
    FaceSpec("fear", "恐惧", "#6C63A8", "◉ ﹏ ◉", "收缩 · 快速颤动"),
    FaceSpec("anxiety", "焦虑", "#8F77B5", "• ﹏ •", "不规则抖动 · 汗滴移动"),
    FaceSpec("anger", "愤怒", "#E15759", "> 皿 <", "眼角收紧 · 咬牙震动"),
    FaceSpec("frustration", "挫败", "#F05D5E", "> ﹏ <", "收紧下垂 · 压力闪烁"),
    FaceSpec("disgust", "厌恶", "#7A9E3A", "¬ へ ¬", "侧视 · 偏嘴回缩"),
    FaceSpec("shame", "羞耻", "#B565A7", "⌒ ︿ ⌒", "低头 · 深色腮红"),
    FaceSpec("guilt", "内疚", "#D7799F", "╯ ︿ ╰", "视线回避 · 缓慢下沉"),
    FaceSpec("jealousy", "嫉妒", "#83A14A", "◉ へ ◉", "侧向盯视 · 不均衡脉冲"),
    FaceSpec("boredom", "无聊", "#7D8597", "─ _ ─", "极慢眨眼 · 低能量漂移"),
    FaceSpec("confusion", "困惑", "#5DADE2", "• ヘ • ?", "两眼错位 · 问号闪现"),
    FaceSpec("neutral", "中性", "#667085", "• ‿ •", "轻微呼吸 · 视线缓慢游移"),
    FaceSpec("offline", "离线", "#3A3F47", "—  —", "暗灰闭眼 · 静止"),
)
FACE_BY_LABEL = {face.label: face for face in FACES}
FACE_BY_KEY = {face.key: face for face in FACES}
ONLINE_FACE_KEYS = tuple(face.key for face in FACES if face.key != "offline")


@dataclass
class AnimationFrame:
    left_eye: str = "dot"
    right_eye: str = "dot"
    mouth: str = "smile"
    eye_y: int = 40
    eye_spread: int = 34
    eye_shift_x: int = 0
    eye_scale: int = 100
    mouth_y: int = 80
    mouth_scale_x: int = 100
    mouth_scale_y: int = 100
    face_x: int = 0
    face_y: int = 0
    cheek_opacity: int = 0
    accent: str = "none"
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
    """生成对齐到 200×120 虚拟像素画布的一帧。"""
    target = AnimationFrame()
    frame = elapsed_ms // FRAME_MS
    drive = 1 + energy // 35
    breath = triangle(frame, 50, drive)
    target.face_y = breath // 2
    target.color_lift = triangle(frame, 50, 2 + energy // 18)
    target.face_opacity = min(255, 96 + elapsed_ms * 159 // 320)

    if face == "joy":
        target.left_eye = target.right_eye = "cap"
        target.mouth = "open_smile"
        target.eye_scale = 100 + breath * 2
        target.mouth_scale_x = 100 + breath * 2
        target.mouth_y = 78 - breath // 2
        target.cheek_opacity = 65 + triangle(frame, 50, 45)
    elif face == "contentment":
        target.left_eye = target.right_eye = "flat"
        target.mouth = "smile"
        target.eye_scale = 100 + breath
        target.mouth_scale_x = 92 + breath * 2
        target.mouth_y = 81 + breath // 2
        target.color_lift = triangle(frame, 75, 5)
    elif face == "interest":
        target.left_eye = target.right_eye = "dot"
        target.mouth = "small_smile"
        target.eye_scale = 105 + breath * 2
        target.eye_spread = 33 - breath // 2
        target.accent = "sparkle"
        target.accent_x = 151
        target.accent_y = 27
    elif face == "hope":
        target.left_eye = target.right_eye = "raised"
        target.mouth = "smile"
        target.eye_y = 41 - breath
        target.face_y = -breath
        target.accent = "rise"
        target.accent_x = 100
        target.accent_y = 23 - breath
    elif face == "relief":
        release = triangle(frame, 62, drive)
        target.left_eye = target.right_eye = "soft"
        target.mouth = "small_smile"
        target.eye_scale = 94 + release
        target.mouth_scale_x = 88 + release * 2
        target.accent = "exhale"
        target.accent_x = 134 + release
        target.accent_y = 79
    elif face == "affection":
        beat = triangle(frame, 20, drive * 2)
        target.left_eye = target.right_eye = "heart"
        target.mouth = "smile"
        target.eye_scale = 94 + beat * 2
        target.cheek_opacity = 100 + triangle(frame, 20, 80)
    elif face == "gratitude":
        target.left_eye = target.right_eye = "cap"
        target.mouth = "small_smile"
        target.face_y = breath
        target.eye_scale = 92 + breath
        target.cheek_opacity = 45 + triangle(frame, 60, 35)
    elif face == "pride":
        target.left_eye = target.right_eye = "proud"
        target.mouth = "proud_smile"
        target.face_y = -breath // 2
        target.eye_scale = 100 + breath
    elif face == "surprise":
        pop = triangle(frame, 24, drive * 2)
        target.left_eye = target.right_eye = "ring"
        target.mouth = "open"
        target.eye_scale = 100 + pop * 2
        target.mouth_scale_x = target.mouth_scale_y = 100 + pop * 2
        if frame % 43 in {0, 1}:
            target.face_x = signed_swing(frame, 4, 1)
    elif face == "sadness":
        drift = triangle(frame, 70, drive)
        target.left_eye = "sad_left"
        target.right_eye = "sad_right"
        target.mouth = "frown"
        target.eye_y = 42 + drift
        target.mouth_y = 84 + drift
        target.mouth_scale_x = 95 - drift * 2
        target.accent = "tear"
        target.accent_x = 145
        target.accent_y = 54 + triangle(frame, 35, 18)
        target.color_lift = 0
    elif face == "fear":
        jitter = signed_swing(frame, 6, drive)
        target.left_eye = target.right_eye = "ring_dot"
        target.mouth = "wave"
        target.face_x = jitter
        target.eye_scale = 108 + triangle(frame, 12, drive * 2)
        target.mouth_scale_x = 90 + triangle(frame, 8, drive * 3)
    elif face == "anxiety":
        jitter = signed_swing(frame, 8, drive)
        target.left_eye = target.right_eye = "dot"
        target.mouth = "wave"
        target.face_x = jitter
        target.eye_scale = 100 + breath * 2
        target.mouth_scale_x = 100 + triangle(frame, 10, drive * 3)
        target.accent = "sweat"
        target.accent_x = 158 + jitter
        target.accent_y = 25 + triangle(frame, 16, 8)
        target.color_lift = triangle(frame, 10, 3 + energy // 14)
    elif face == "anger":
        tension = triangle(frame, 20, drive)
        target.left_eye = "greater"
        target.right_eye = "less"
        target.mouth = "teeth"
        target.eye_y = 42 + tension // 2
        target.eye_scale = 100 + tension * 2
        target.mouth_y = 81 - tension // 2
        target.mouth_scale_x = 100 + tension * 2
        target.color_lift = triangle(frame, 20, 4 + energy // 12)
        if energy >= 60 and frame % 41 in {0, 1, 2}:
            target.face_x = (-1, 1, -1)[frame % 41]
    elif face == "frustration":
        squeeze = triangle(frame, 26, drive)
        target.left_eye = "greater"
        target.right_eye = "less"
        target.mouth = "wave"
        target.eye_scale = 95 + squeeze * 2
        target.mouth_y = 83 + squeeze
        target.accent = "stress"
        target.accent_x = 153
        target.accent_y = 25
    elif face == "disgust":
        recoil = triangle(frame, 34, drive)
        target.left_eye = "half"
        target.right_eye = "flat"
        target.mouth = "skew_frown"
        target.eye_shift_x = recoil
        target.mouth_y = 82 + recoil
        target.mouth_scale_x = 92 - recoil * 2
        target.color_lift = triangle(frame, 34, 6)
    elif face == "shame":
        hide = triangle(frame, 42, drive)
        target.left_eye = target.right_eye = "cap"
        target.mouth = "frown"
        target.eye_y = 42 + hide
        target.eye_scale = 88 - hide
        target.mouth_y = 81 + hide // 2
        target.mouth_scale_x = 82 + breath
        target.cheek_opacity = 135 + triangle(frame, 20, 90)
        target.color_lift = triangle(frame, 42, 8)
    elif face == "guilt":
        sink = triangle(frame, 65, drive)
        target.left_eye = "guilt_left"
        target.right_eye = "guilt_right"
        target.mouth = "small_frown"
        target.face_y = 2 + sink
        target.eye_shift_x = -2
        target.mouth_scale_x = 86 - sink
    elif face == "jealousy":
        glance = signed_swing(frame, 46, 4)
        target.left_eye = target.right_eye = "ring_dot"
        target.mouth = "skew_frown"
        target.eye_shift_x = glance
        target.mouth_scale_x = 92
        target.color_lift = triangle(frame, 23, 7)
    elif face == "boredom":
        target.left_eye = target.right_eye = "flat"
        target.mouth = "flat"
        target.face_y = triangle(frame, 110, 1)
        target.eye_scale = 94
        target.color_lift = triangle(frame, 100, 2)
    elif face == "confusion":
        wobble = signed_swing(frame, 34, 2)
        target.left_eye = "dot"
        target.right_eye = "ring"
        target.mouth = "skew_frown"
        target.eye_y = 40 + wobble
        target.eye_shift_x = wobble
        target.accent = "question"
        target.accent_x = 158
        target.accent_y = 27 + triangle(frame, 40, 2)
    elif face == "offline":
        target.left_eye = target.right_eye = "flat"
        target.mouth = "none"
        target.face_opacity = 180
        target.color_lift = 0
    else:
        glance = signed_swing(frame, 80, 2)
        target.left_eye = target.right_eye = "dot"
        target.mouth = "small_smile"
        target.eye_shift_x = glance
        target.eye_scale = 100 + breath
        target.mouth_y = 81 + breath // 2
        target.color_lift = triangle(frame, 80, 3)

    if face not in {"offline", "contentment", "boredom"}:
        period = 31 if face in {"fear", "anxiety"} else 47 if face == "surprise" else 59
        closed_frames = 2 if energy >= 60 else 1
        if (frame + period // 2) % period < closed_frames:
            target.left_eye = target.right_eye = "flat"
    return target


def lift_color(hex_color: str, percent: int) -> str:
    rgb = tuple(int(hex_color[index : index + 2], 16) for index in (1, 3, 5))
    lifted = tuple(value + (255 - value) * percent // 100 for value in rgb)
    return "#" + "".join(f"{value:02X}" for value in lifted)


def blend_color(background: str, foreground: str, opacity: int) -> str:
    bg = tuple(int(background[index : index + 2], 16) for index in (1, 3, 5))
    fg = tuple(int(foreground[index : index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(
        (back * (255 - opacity) + front * opacity) // 255
        for back, front in zip(bg, fg, strict=True)
    )
    return "#" + "".join(f"{value:02X}" for value in mixed)


class MoodDisplayPreview:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at
        self.current_face = "anger"
        root.title("ARMI 像素颜表情预览")
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
        self.status = ttk.Label(root, padding=(14, 10, 14, 14), anchor="center")
        self.status.grid(row=2, column=0, sticky="ew")
        self._tick()

    def _select_face(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.current_face = FACE_BY_LABEL[self.face_label.get()].key
        self.started_at = time.monotonic()
        self.last_auto_change = self.started_at

    def _block(self, x: int, y: int, width: int, height: int, color: str) -> None:
        self.canvas.create_rectangle(
            x * PIXEL_SCALE,
            y * PIXEL_SCALE,
            (x + width) * PIXEL_SCALE - 1,
            (y + height) * PIXEL_SCALE - 1,
            fill=color,
            outline="",
        )

    def _pixel_line(
        self, points: list[tuple[int, int]], color: str, thickness: int = 2
    ) -> None:
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            dx = abs(x1 - x0)
            sx = 1 if x0 < x1 else -1
            dy = -abs(y1 - y0)
            sy = 1 if y0 < y1 else -1
            error = dx + dy
            while True:
                self._block(
                    x0 - thickness // 2,
                    y0 - thickness // 2,
                    thickness,
                    thickness,
                    color,
                )
                if x0 == x1 and y0 == y1:
                    break
                twice = 2 * error
                if twice >= dy:
                    error += dy
                    x0 += sx
                if twice <= dx:
                    error += dx
                    y0 += sy

    @staticmethod
    def _scaled(
        points: list[tuple[int, int]], cx: int, cy: int, scale: int
    ) -> list[tuple[int, int]]:
        return [(cx + x * scale // 100, cy + y * scale // 100) for x, y in points]

    def _draw_eye(self, kind: str, cx: int, cy: int, scale: int, color: str) -> None:
        paths = {
            "flat": [[(-12, 0), (12, 0)]],
            "cap": [[(-14, 5), (-10, 1), (-5, -2), (0, -3), (5, -2), (10, 1), (14, 5)]],
            "soft": [[(-11, 3), (-6, 0), (0, -2), (6, 0), (11, 3)]],
            "raised": [[(-12, 4), (-6, 0), (1, -3), (7, -3), (12, -1)]],
            "proud": [[(-12, 1), (-4, -1), (4, -1), (12, 1)]],
            "greater": [[(-9, -8), (2, 0), (-9, 8)]],
            "less": [[(9, -8), (-2, 0), (9, 8)]],
            "sad_left": [[(-12, -3), (-4, 2), (5, 5), (12, 5)]],
            "sad_right": [[(-12, 5), (-5, 5), (4, 2), (12, -3)]],
            "guilt_left": [[(-11, -4), (-7, 1), (-2, 5), (5, 6), (11, 4)]],
            "guilt_right": [[(-11, 4), (-5, 6), (2, 5), (7, 1), (11, -4)]],
            "half": [[(-12, -2), (-4, 3), (5, 4), (12, 1)]],
        }
        if kind == "dot":
            for y, width in enumerate((3, 5, 7, 7, 7, 5, 3), start=-3):
                self._block(cx - width // 2, cy + y, width, 1, color)
            return
        if kind == "star":
            self._pixel_line(self._scaled([(0, -10), (0, 10)], cx, cy, scale), color, 2)
            self._pixel_line(self._scaled([(-10, 0), (10, 0)], cx, cy, scale), color, 2)
            self._pixel_line(self._scaled([(-7, -7), (7, 7)], cx, cy, scale), color, 1)
            self._pixel_line(self._scaled([(7, -7), (-7, 7)], cx, cy, scale), color, 1)
            return
        if kind == "heart":
            heart = [
                (-10, -4),
                (-7, -8),
                (-2, -8),
                (0, -4),
                (2, -8),
                (7, -8),
                (10, -4),
                (9, 1),
                (0, 10),
                (-9, 1),
                (-10, -4),
            ]
            self._pixel_line(self._scaled(heart, cx, cy, scale), color, 2)
            return
        if kind in {"ring", "ring_dot"}:
            ring = [
                (-7, -9),
                (7, -9),
                (10, -6),
                (10, 6),
                (7, 9),
                (-7, 9),
                (-10, 6),
                (-10, -6),
                (-7, -9),
            ]
            self._pixel_line(self._scaled(ring, cx, cy, scale), color, 2)
            if kind == "ring_dot":
                size = max(3, 5 * scale // 100)
                self._block(cx - size // 2, cy - size // 2, size, size, color)
            return
        for path in paths[kind]:
            self._pixel_line(
                self._scaled(path, cx, cy, scale),
                color,
                3 if kind in {"greater", "less"} else 2,
            )

    def _draw_mouth(
        self, kind: str, cx: int, cy: int, scale_x: int, scale_y: int, color: str
    ) -> None:
        paths = {
            "smile": [[(-13, -3), (-9, 1), (-5, 4), (0, 6), (5, 4), (9, 1), (13, -3)]],
            "proud_smile": [[(-12, -1), (-6, 2), (0, 3), (6, 2), (12, -1)]],
            "small_smile": [[(-9, -2), (-5, 1), (0, 3), (5, 1), (9, -2)]],
            "small_frown": [[(-9, 3), (-5, 0), (0, -2), (5, 0), (9, 3)]],
            "frown": [[(-13, 4), (-8, 0), (-3, -3), (0, -4), (3, -3), (8, 0), (13, 4)]],
            "omega": [
                [
                    (-15, -4),
                    (-13, 2),
                    (-9, 7),
                    (-5, 6),
                    (0, 0),
                    (5, 6),
                    (9, 7),
                    (13, 2),
                    (15, -4),
                ]
            ],
            "wave": [
                [
                    (-14, 1),
                    (-10, -2),
                    (-6, 2),
                    (-2, -2),
                    (2, 2),
                    (6, -2),
                    (10, 2),
                    (14, -1),
                ]
            ],
            "skew_frown": [[(-12, 2), (-6, -2), (0, -3), (7, 0), (13, 5)]],
            "flat": [[(-11, 0), (11, 0)]],
        }
        if kind == "none":
            return
        if kind == "teeth":
            left = cx - 15 * scale_x // 100
            right = cx + 15 * scale_x // 100
            top = cy - 6 * scale_y // 100
            bottom = cy + 6 * scale_y // 100
            self._pixel_line(
                [
                    (left, top),
                    (right, top),
                    (right, bottom),
                    (left, bottom),
                    (left, top),
                ],
                color,
                2,
            )
            self._pixel_line([(left, cy), (right, cy)], color, 1)
            for offset in (-7, 0, 7):
                x = cx + offset * scale_x // 100
                self._pixel_line([(x, top), (x, bottom)], color, 1)
            return
        if kind in {"open", "open_smile"}:
            width = (8 if kind == "open" else 13) * scale_x // 100
            top = cy - (8 if kind == "open" else 4) * scale_y // 100
            bottom = cy + 8 * scale_y // 100
            outline = [
                (cx - width, top),
                (cx + width, top),
                (cx + width + 2, cy),
                (cx, bottom),
                (cx - width - 2, cy),
                (cx - width, top),
            ]
            self._pixel_line(outline, color, 2)
            return
        for path in paths[kind]:
            scaled = [
                (cx + x * scale_x // 100, cy + y * scale_y // 100) for x, y in path
            ]
            self._pixel_line(scaled, color, 2)

    def _draw_accent(self, kind: str, x: int, y: int, color: str) -> None:
        if kind in {"tear", "sweat"}:
            height = 6 if kind == "tear" else 5
            self._pixel_line(
                [
                    (x, y - height),
                    (x - 3, y),
                    (x, y + height),
                    (x + 3, y),
                    (x, y - height),
                ],
                color,
                2,
            )
        elif kind == "sparkle":
            self._pixel_line([(x, y - 5), (x, y + 5)], color, 1)
            self._pixel_line([(x - 5, y), (x + 5, y)], color, 1)
        elif kind == "rise":
            self._pixel_line([(x - 4, y + 3), (x, y - 2), (x + 4, y + 3)], color, 1)
        elif kind == "exhale":
            self._pixel_line([(x, y), (x + 5, y - 1), (x + 10, y)], color, 1)
        elif kind == "stress":
            self._pixel_line([(x - 5, y - 5), (x, y), (x - 5, y + 5)], color, 2)
        elif kind == "question":
            self._pixel_line(
                [
                    (x - 4, y - 5),
                    (x, y - 8),
                    (x + 4, y - 5),
                    (x + 4, y - 1),
                    (x, y + 2),
                    (x, y + 5),
                ],
                color,
                2,
            )
            self._block(x - 1, y + 9, 2, 2, color)

    def _draw(self, frame: AnimationFrame, expression_color: str) -> None:
        color = blend_color("#000000", expression_color, frame.face_opacity)
        self.canvas.delete("all")
        center_x = LOGICAL_WIDTH // 2 + frame.face_x
        eye_y = frame.eye_y + frame.face_y
        self._draw_eye(
            frame.left_eye,
            center_x - frame.eye_spread + frame.eye_shift_x,
            eye_y,
            frame.eye_scale,
            color,
        )
        self._draw_eye(
            frame.right_eye,
            center_x + frame.eye_spread + frame.eye_shift_x,
            eye_y,
            frame.eye_scale,
            color,
        )
        self._draw_mouth(
            frame.mouth,
            center_x,
            frame.mouth_y + frame.face_y,
            frame.mouth_scale_x,
            frame.mouth_scale_y,
            color,
        )
        if frame.cheek_opacity:
            cheek_color = blend_color(
                "#000000",
                expression_color,
                frame.cheek_opacity * frame.face_opacity // 255,
            )
            for cheek_x in (center_x - 53, center_x + 53):
                for offset in (-5, 0, 5):
                    self._pixel_line(
                        [
                            (cheek_x + offset - 2, 69 + frame.face_y),
                            (cheek_x + offset + 2, 65 + frame.face_y),
                        ],
                        cheek_color,
                        1,
                    )
        self._draw_accent(
            frame.accent,
            frame.accent_x + frame.face_x,
            frame.accent_y + frame.face_y,
            color,
        )

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
        elapsed_ms = max(0, math.floor((now - self.started_at) * 1000))
        frame = animation_frame(self.current_face, energy, elapsed_ms)
        spec = FACE_BY_KEY[self.current_face]
        self._draw(frame, lift_color(spec.color, frame.color_lift))
        self.status.configure(
            text=f"{spec.label}    {spec.sketch}    {spec.motion}    {spec.color}    energy {energy}"
        )
        self.root.after(FRAME_MS, self._tick)


def smoke_test() -> None:
    valid_eyes = {
        "dot",
        "flat",
        "cap",
        "soft",
        "raised",
        "proud",
        "star",
        "heart",
        "ring",
        "ring_dot",
        "greater",
        "less",
        "sad_left",
        "sad_right",
        "guilt_left",
        "guilt_right",
        "half",
    }
    valid_mouths = {
        "none",
        "smile",
        "proud_smile",
        "small_smile",
        "small_frown",
        "frown",
        "omega",
        "wave",
        "teeth",
        "skew_frown",
        "flat",
        "open",
        "open_smile",
    }
    emotion_faces = FACES[:20]
    assert len({face.key for face in emotion_faces}) == 20
    assert len({face.sketch for face in emotion_faces}) == 20
    assert len({face.color for face in emotion_faces}) == 20
    for face in FACE_BY_KEY:
        for energy in (0, 50, 100):
            for elapsed_ms in (0, 80, 320, 4_000):
                frame = animation_frame(face, energy, elapsed_ms)
                assert frame.left_eye in valid_eyes
                assert frame.right_eye in valid_eyes
                assert frame.mouth in valid_mouths
                assert 0 <= frame.face_opacity <= 255
                assert 0 <= frame.color_lift <= 100
    angry = animation_frame("anger", 70, 800)
    assert (angry.left_eye, angry.mouth, angry.right_eye) == (
        "greater",
        "teeth",
        "less",
    )
    assert lift_color("#000000", 100) == "#FFFFFF"
    assert blend_color("#000000", "#FFFFFF", 255) == "#FFFFFF"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-test", action="store_true", help="只验证动画计算且不打开窗口"
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
