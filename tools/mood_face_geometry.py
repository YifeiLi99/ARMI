"""Original electronic faces, drawn from independent eyes and a small mouth."""

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = (768, 432)
CYAN = "#52D9F5"
# Eye pair, mouth. Coordinates stay fixed across emotions; no text is stretched.
STYLES = {
    "joy": ("squeeze", "w"),
    "contentment": ("happy", "smile"),
    "interest": ("round", "v"),
    "hope": ("shine", "smile"),
    "relief": ("closed", "smile"),
    "affection": ("heart", "w"),
    "gratitude": ("happy", "w"),
    "pride": ("confident", "smirk"),
    "surprise": ("round", "o"),
    "sadness": ("sad", "frown"),
    "fear": ("frightened", "gasp"),
    "anxiety": ("tense", "wave"),
    "anger": ("angry", "grit"),
    "frustration": ("squeeze", "wave"),
    "disgust": ("squint", "disgust"),
    "shame": ("bashful", "small"),
    "guilt": ("remorse", "frown"),
    "jealousy": ("side", "pout"),
    "boredom": ("double", "small"),
    "confusion": ("questioning", "slant"),
    "neutral": ("resting", "small"),
    "offline": ("closed", "small"),
}


def render_face(key: str) -> Image.Image:
    """Return an antialiased A8 mask with restrained glow and scan lines."""
    scale = 3
    image = Image.new("L", (SIZE[0] * scale, SIZE[1] * scale), 0)
    draw = ImageDraw.Draw(image)

    def line(points: list[tuple[float, float]], width: int = 16) -> None:
        xy = [(round(x * scale), round(y * scale)) for x, y in points]
        draw.line(xy, fill=255, width=width * scale, joint="curve")
        radius = width * scale / 2
        for x, y in (xy[0], xy[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)

    def oval(x: float, y: float, rx: float, ry: float, ring: bool = False) -> None:
        box = ((x - rx) * scale, (y - ry) * scale, (x + rx) * scale, (y + ry) * scale)
        draw.ellipse(box, fill=None if ring else 255, outline=255, width=14 * scale)

    eye, mouth = STYLES[key]
    for index, cx in enumerate((160, 608)):
        cy = 170
        inward = 1 if index == 0 else -1

        def path(
            points: list[tuple[float, float]],
            width: int = 16,
            cx: int = cx,
            cy: int = cy,
            inward: int = inward,
        ) -> None:
            line([(cx + x * inward, cy + y) for x, y in points], width)

        if eye in ("round", "shine"):
            oval(cx, cy, 54, 54)
            if eye == "shine":
                draw.ellipse(
                    (
                        (cx - 23) * scale,
                        (cy - 31) * scale,
                        (cx - 3) * scale,
                        (cy - 11) * scale,
                    ),
                    fill=0,
                )
        elif eye == "heart":
            points = [
                (-52, -13),
                (-50, -34),
                (-34, -46),
                (-15, -45),
                (0, -29),
                (15, -45),
                (34, -46),
                (50, -34),
                (52, -13),
                (40, 9),
                (0, 49),
                (-40, 9),
            ]
            draw.polygon(
                [((cx + x) * scale, (cy + y) * scale) for x, y in points], fill=255
            )
        elif eye == "squeeze":
            path([(-45, -44), (39, 0), (-45, 44)], 21)
        elif eye == "happy":
            path(
                [
                    (-49, 17),
                    (-32, -8),
                    (-15, -23),
                    (0, -28),
                    (15, -23),
                    (32, -8),
                    (49, 17),
                ],
                19,
            )
        elif eye in ("double", "closed"):
            path([(-51, 0), (51, 0)])
            if eye == "double":
                path([(-51, -30), (51, -30)])
        elif eye == "confident":
            path([(-51, -28), (48, 3)], 20)
        elif eye == "angry":
            points = [(-52, -33), (49, 4), (33, 27), (-32, 27), (-51, 9)]
            draw.polygon(
                [((cx + x * inward) * scale, (cy + y) * scale) for x, y in points],
                fill=255,
            )
        elif eye == "sad":
            path([(-49, 6), (47, -26)], 18)
            # A pointed top joins a round drop, separated from the eyelid.
            tx = cx - 28 * inward
            draw.polygon(
                [
                    ((tx - 14) * scale, (cy + 63) * scale),
                    (tx * scale, (cy + 34) * scale),
                    ((tx + 14) * scale, (cy + 63) * scale),
                ],
                fill=255,
            )
            oval(tx, cy + 65, 14, 16)
        elif eye == "frightened":
            oval(cx, cy, 43, 57, True)
            oval(cx, cy + 3, 9, 19)
            path([(-43, -76), (0, -89), (43, -77)], 11)
        elif eye == "tense":
            path([(-47, 8), (-20, -7), (17, -13), (46, -7)], 20)
            path([(-44, -36), (40, -58)], 11)
        elif eye == "squint":
            path([(-49, -4), (0, 9), (45, 0)], 19)
            path([(-39, -36), (42, -25 if index == 0 else -48)], 11)
        elif eye == "bashful":
            path([(-42, 2), (-15, 20), (15, 20), (42, 2)], 15)
            for dx in (-24, 0, 24):
                path([(dx - 5, 56), (dx + 5, 39)], 8)
        elif eye == "remorse":
            path([(-44, -39), (39, -61)], 11)
            path([(-43, 3), (0, 15), (43, 3)], 16)
        elif eye == "side":
            path([(-48, -21), (47, -8)], 15)
            path([(-43, 28), (43, 28)], 10)
            # Both pupils look to the same side, inside the narrowed lids.
            oval(cx + 23, cy + 7, 12, 15)
        elif eye == "questioning":
            oval(cx, cy, 30, 35)
            if index == 0:
                path([(-40, -67), (0, -81), (40, -67)], 11)
            else:
                path([(-40, -42), (40, -24)], 11)
        elif eye == "resting":
            oval(cx, cy, 29, 36)

    # The mouth stays within 112 x 56, substantially smaller than either eye pair.
    mx, my = 384, 278
    mouths = {
        "w": [
            (-49, -12),
            (-42, 13),
            (-26, 20),
            (-12, 14),
            (0, 0),
            (12, 14),
            (26, 20),
            (42, 13),
            (49, -12),
        ],
        "smile": [(-46, -10), (-30, 12), (0, 23), (30, 12), (46, -10)],
        "v": [(-29, -16), (0, 24), (29, -16)],
        "flat": [(-48, 0), (48, 0)],
        "small": [(-25, 0), (25, 0)],
        "frown": [(-43, 18), (-23, 0), (0, -9), (23, 0), (43, 18)],
        "wave": [(-49, 0), (-32, -10), (-16, 9), (0, -9), (16, 9), (32, -10), (49, 0)],
        "smirk": [(-43, 8), (0, 8), (27, -1), (43, -17)],
        "slant": [(-32, 12), (32, -10)],
        "disgust": [(-42, 15), (-21, -8), (7, -8), (34, 7)],
        "pout": [(-36, 1), (0, 9), (36, 1)],
    }
    if mouth == "o":
        oval(mx, my, 24, 31, True)
    elif mouth == "gasp":
        oval(mx, my, 28, 34)
    elif mouth == "grit":
        line(
            [
                (mx - 42, my + 12),
                (mx - 33, my - 12),
                (mx + 33, my - 12),
                (mx + 42, my + 12),
                (mx - 42, my + 12),
            ],
            10,
        )
        line([(mx - 36, my), (mx + 36, my)], 6)
    else:
        line([(mx + x, my + y) for x, y in mouths[mouth]], 13)

    if key == "offline":
        for zx, zy, size in ((516, 98, 18), (566, 75, 24), (628, 45, 30)):
            line(
                [(zx, zy), (zx + size, zy), (zx, zy + size), (zx + size, zy + size)], 6
            )

    ink = image.resize(SIZE, Image.Resampling.LANCZOS)
    glow = ink.filter(ImageFilter.GaussianBlur(3)).point([p // 5 for p in range(256)])
    # Subtle scan lines leave silhouettes legible, including at reduced brightness.
    scan = Image.new("L", SIZE, 0)
    scan_draw = ImageDraw.Draw(scan)
    for y in range(SIZE[1]):
        scan_draw.line((0, y, SIZE[0], y), fill=185 if y % 8 < 2 else 255)
    return ImageChops.lighter(ImageChops.multiply(ink, scan), glow)
