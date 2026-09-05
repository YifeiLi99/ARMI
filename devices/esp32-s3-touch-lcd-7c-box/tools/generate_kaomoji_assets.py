"""Generate geometric electronic face A8 assets (no font dependency)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.mood_display_preview import FACES
from tools.mood_face_geometry import CYAN, render_face


def generate(output_dir: Path, preview_path: Path | None) -> None:
    binary = bytearray()
    catalog = ["/* Generated geometric faces; do not edit. */"]
    sheet = Image.new("RGB", (1600, 11 * 512), "#181b22")
    draw = ImageDraw.Draw(sheet)
    for index, face in enumerate(FACES):
        mask = render_face(face.key)
        offset = len(binary)
        binary.extend(mask.tobytes())
        catalog.append(
            f'{{"{face.expression}", {offset}U, {mask.width}U, {mask.height}U}}, '
            f"/* {face.key.upper()}, {face.label} */"
        )
        x, y = (index % 2) * 800, (index // 2) * 512
        draw.rectangle((x, y + 32, x + 799, y + 511), fill="black")
        sheet.paste(Image.new("RGB", mask.size, CYAN), (x + 16, y + 56), mask)
        draw.text((x + 12, y + 8), face.key, fill="#89909E")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mood_text_assets.bin").write_bytes(binary)
    (output_dir / "mood_text_catalog.inc").write_text(
        "\n".join(catalog) + "\n", encoding="utf-8", newline="\n"
    )
    if preview_path:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(preview_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parents[1] / "main"
    )
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    generate(args.output_dir, args.preview)


if __name__ == "__main__":
    main()
