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
    "fear": ("ring", "o"),
    "anxiety": ("worried", "wave"),
    "anger": ("angry", "flat"),
    "frustration": ("squeeze", "wave"),
    "disgust": ("half", "frown"),
    "shame": ("down", "small"),
    "guilt": ("worried", "small"),
    "jealousy": ("side", "flat"),
    "boredom": ("double", "small"),
    "confusion": ("uneven", "slant"),
    "neutral": ("double", "flat"),
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

        if eye in ("round", "ring", "shine"):
            oval(cx, cy, 54, 54, eye == "ring")
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
        elif eye in ("angry", "confident"):
            path([(-51, -28), (48, 3)], 20)
            if eye == "angry":
                path([(-36, 29), (33, 29)], 13)
        elif eye in ("sad", "worried"):
            path([(-49, 6), (47, -26)], 18)
            if eye == "sad":
                path([(-22, 35), (-22, 79)], 13)
            else:
                oval(cx, cy + 27, 14, 22)
        elif eye in ("half", "side"):
            path([(-51, -20), (51, -20)])
            oval(cx + (26 if eye == "side" else 0), cy + 13, 16, 23)
        elif eye == "down":
            path([(-44, 7), (0, 29), (44, 7)], 17)
        elif eye == "uneven":
            if index == 0:
                oval(cx, cy, 43, 43)
            else:
                path([(-45, -18), (45, -18)])

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
    }
    if mouth == "o":
        oval(mx, my, 24, 31, True)
    else:
        line([(mx + x, my + y) for x, y in mouths[mouth]], 13)

    ink = image.resize(SIZE, Image.Resampling.LANCZOS)
    glow = ink.filter(ImageFilter.GaussianBlur(3)).point([p // 5 for p in range(256)])
    # Subtle scan lines leave silhouettes legible, including at reduced brightness.
    scan = Image.new("L", SIZE, 0)
    scan_draw = ImageDraw.Draw(scan)
    for y in range(SIZE[1]):
        scan_draw.line((0, y, SIZE[0], y), fill=185 if y % 8 < 2 else 255)
    return ImageChops.lighter(ImageChops.multiply(ink, scan), glow)
