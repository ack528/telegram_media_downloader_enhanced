"""Generate the Windows icon used by the packaged executable."""

from __future__ import annotations

import math
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "tdl_logo.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _rgba_at(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    cx = cy = (size - 1) / 2
    radius = size * 0.43
    dx = x - cx
    dy = y - cy
    dist = math.sqrt(dx * dx + dy * dy)
    if dist > radius:
        return 0, 0, 0, 0

    t = (x + y) / (2 * size)
    blue = int(255 - 55 * t)
    green = int(166 - 75 * t)
    base = (22, green, blue, 255)

    # Paper plane body.
    nx = x / size
    ny = y / size
    if 0.22 < nx < 0.78 and 0.23 < ny < 0.68 and ny > -0.52 * nx + 0.43 and ny < -0.16 * nx + 0.76:
        return 246, 251, 255, 255
    if 0.38 < nx < 0.62 and 0.48 < ny < 0.82:
        return 231, 245, 255, 255

    # Download arrow.
    arrow_x = abs(nx - 0.5)
    if 0.39 < ny < 0.67 and arrow_x < 0.055:
        return 255, 255, 255, 255
    if 0.56 < ny < 0.74 and arrow_x < (ny - 0.49) * 0.56:
        return 255, 255, 255, 255
    if 0.75 < ny < 0.82 and arrow_x < 0.15:
        return 255, 255, 255, 255

    return base


def _bmp_icon_image(size: int) -> bytes:
    pixels = bytearray()
    mask = bytearray()
    row_mask_bytes = ((size + 31) // 32) * 4
    for y in range(size - 1, -1, -1):
        mask_row = bytearray(row_mask_bytes)
        for x in range(size):
            r, g, b, a = _rgba_at(x, y, size)
            pixels.extend((b, g, r, a))
            if a == 0:
                mask_row[x // 8] |= 0x80 >> (x % 8)
        mask.extend(mask_row)

    header = struct.pack(
        "<IIIHHIIIIII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixels) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + bytes(pixels) + bytes(mask)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [_bmp_icon_image(size) for size in SIZES]
    header_size = 6 + 16 * len(images)
    offset = header_size
    directory = bytearray()
    for size, image in zip(SIZES, images):
        width = 0 if size == 256 else size
        directory.extend(
            struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(image), offset)
        )
        offset += len(image)
    OUT.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + bytes(directory) + b"".join(images))


if __name__ == "__main__":
    main()
