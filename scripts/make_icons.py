"""Draw the placeholder app icons (PNG) with the standard library only.

    python scripts/make_icons.py

Writes static/icons/: icon-192.png, icon-512.png, maskable-512.png and
apple-touch-icon.png (180x180). A washing-machine door on a blue square;
replace these files when the final design arrives (keep the names and sizes).
The maskable icon keeps the drawing inside the central "safe zone" (80%), as
Android may crop it to a circle.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
BLUE = (29, 78, 216)
WHITE = (255, 255, 255)
LIGHT = (191, 219, 254)


def _png(width, height, pixel):
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height)
    )

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def _icon(size, scale):
    """`scale` shrinks the drawing towards the centre (1 = full size)."""
    centre = size / 2

    def pixel(x, y):
        # Coordinates from -1 to 1 around the centre, divided by the scale.
        u = (x + 0.5 - centre) / (centre * scale)
        v = (y + 0.5 - centre) / (centre * scale)
        door = (u * u + (v - 0.12) ** 2) ** 0.5
        if 0.46 <= door <= 0.6:
            return WHITE  # door ring
        if door < 0.46 and v > 0.2:
            return LIGHT  # water in the drum
        if -0.62 <= v <= -0.5 and -0.5 <= u <= 0.1:
            return WHITE  # control panel
        if -0.64 <= v <= -0.48 and 0.3 <= u <= 0.46:
            return WHITE  # knob
        return BLUE

    return _png(size, size, pixel)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "icon-192.png": _icon(192, 1),
        "icon-512.png": _icon(512, 1),
        "maskable-512.png": _icon(512, 0.75),
        "apple-touch-icon.png": _icon(180, 0.9),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote static/icons/{name}")


if __name__ == "__main__":
    main()
