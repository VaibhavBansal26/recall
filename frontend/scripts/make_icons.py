"""Render the PWA icons (an indigo orb on a dark tile) with only the standard library.

Run from the frontend folder: python3 scripts/make_icons.py
Outputs to public/icons/. The committed PNGs are the source of truth; this just regenerates them.
"""

import math
import struct
import zlib
from pathlib import Path

BG = (15, 16, 32)
OUT = Path(__file__).resolve().parent.parent / "public" / "icons"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def pixel(nx: float, ny: float, orb: float) -> tuple[float, float, float]:
    """Colour at a point in [-0.5, 0.5] units from the centre; orb is the orb radius."""
    r = math.hypot(nx, ny)
    colour = BG
    ring = 1.38 * orb
    if abs(r - ring) < 0.035 * orb:
        colour = tuple(lerp(c, i, 0.35) for c, i in zip(BG, (129, 140, 248)))
    if r <= orb:
        # Radial gradient with the highlight up and to the left.
        hx, hy = nx + 0.35 * orb, ny + 0.35 * orb
        t = min(1.0, math.hypot(hx, hy) / (1.5 * orb))
        top, bottom = (165, 180, 252), (79, 70, 229)
        colour = tuple(lerp(a, b, t) for a, b in zip(top, bottom))
    return colour  # type: ignore[return-value]


def render(size: int, orb: float) -> bytes:
    rows = bytearray()
    ss = 2  # 2x2 supersampling for smooth edges
    for y in range(size):
        rows.append(0)  # PNG filter: none
        for x in range(size):
            acc = [0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    nx = (x + (sx + 0.5) / ss) / size - 0.5
                    ny = (y + (sy + 0.5) / ss) / size - 0.5
                    for i, v in enumerate(pixel(nx, ny, orb)):
                        acc[i] += v
            rows.extend(int(round(v / (ss * ss))) for v in acc)
    return bytes(rows)


def png(size: int, orb: float) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(render(size, orb), 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    # "any" icons use a bigger orb; the maskable one keeps everything inside the 80% safe zone.
    for name, size, orb in [
        ("icon-192.png", 192, 0.27),
        ("icon-512.png", 512, 0.27),
        ("apple-touch-icon.png", 180, 0.27),
        ("maskable-512.png", 512, 0.20),
    ]:
        (OUT / name).write_bytes(png(size, orb))
        print("wrote", OUT / name)
