"""
Generate icon.png (512x512) for the Hive Schedule Manager integration.

No dependencies required — uses only Python standard library.
Run from any directory:
    python3 generate_icon_png.py

Output: icon.png in the same directory as this script.
Note: pure-Python rendering is slow (~10-30 s for 512x512). Be patient.
"""
import struct
import zlib
import math
import os

W, H = 512, 512

# Colours
ORANGE      = (255, 105,   0)
DARK_ORANGE = (204,  85,   0)
WHITE       = (255, 255, 255)
BG          = (  0,   0,   0,   0)  # transparent (RGBA)

# ── Geometry ─────────────────────────────────────────────────────────────────

CX, CY = 256, 256
HEX_R  = 228   # flat-top hexagon, "radius" = half-width

CAL_X1, CAL_Y1 = 148, 182
CAL_X2, CAL_Y2 = 364, 368
HEADER_H = 52
CORNER_R = 16

RING_R  = 11
RING1_X, RING1_Y = 202, CAL_Y1
RING2_X, RING2_Y = 310, CAL_Y1

DOT_R     = 12
HI_OUTER  = 16
HI_INNER  = 10
DOT_ROW1  = CAL_Y1 + HEADER_H + 44
DOT_ROW2  = CAL_Y1 + HEADER_H + 92
DOT_COLS  = [202, 256, 310]


def in_flat_hexagon(x, y, cx, cy, r):
    """Return True if (x,y) is inside a flat-top regular hexagon."""
    dx = abs(x - cx)
    dy = abs(y - cy)
    if dx > r:
        return False
    h = r * (3 ** 0.5) / 2          # half-height
    if dy > h:
        return False
    # Edge cut: the slanted edges reduce the corners
    if dx * (3 ** 0.5) / 2 + dy / 2 > h:
        return False
    return True


def in_rounded_rect(x, y, x1, y1, x2, y2, r):
    if x < x1 or x > x2 or y < y1 or y > y2:
        return False
    # corner zones
    if x < x1 + r and y < y1 + r:
        return (x - (x1 + r)) ** 2 + (y - (y1 + r)) ** 2 <= r * r
    if x > x2 - r and y < y1 + r:
        return (x - (x2 - r)) ** 2 + (y - (y1 + r)) ** 2 <= r * r
    if x < x1 + r and y > y2 - r:
        return (x - (x1 + r)) ** 2 + (y - (y2 - r)) ** 2 <= r * r
    if x > x2 - r and y > y2 - r:
        return (x - (x2 - r)) ** 2 + (y - (y2 - r)) ** 2 <= r * r
    return True


def dist2(ax, ay, bx, by):
    return (ax - bx) ** 2 + (ay - by) ** 2


# ── Render ───────────────────────────────────────────────────────────────────

print(f"Rendering {W}x{H} icon … (this may take 10-30 s)")
rows = []

for y in range(H):
    if y % 64 == 0:
        print(f"  row {y}/{H}")
    row = bytearray()
    row.append(0)       # PNG filter: None
    for x in range(W):

        # Background: transparent outside hexagon
        if not in_flat_hexagon(x, y, CX, CY, HEX_R):
            row += bytes([0, 0, 0, 0])
            continue

        r, g, b, a = *ORANGE, 255   # default: orange hex

        # Binding rings (above calendar top edge)
        if dist2(x, y, RING1_X, RING1_Y) <= RING_R * RING_R:
            r, g, b = WHITE
        elif dist2(x, y, RING2_X, RING2_Y) <= RING_R * RING_R:
            r, g, b = WHITE

        elif in_rounded_rect(x, y, CAL_X1, CAL_Y1, CAL_X2, CAL_Y2, CORNER_R):
            in_header = y < CAL_Y1 + HEADER_H
            r, g, b = DARK_ORANGE if in_header else WHITE

            # Grid dots
            placed = False
            for col in DOT_COLS:
                for row_y in (DOT_ROW1, DOT_ROW2):
                    highlighted = (col == 310 and row_y == DOT_ROW2)
                    d2 = dist2(x, y, col, row_y)
                    if highlighted:
                        if d2 <= HI_OUTER * HI_OUTER:
                            r, g, b = DARK_ORANGE
                            if d2 <= HI_INNER * HI_INNER:
                                r, g, b = WHITE
                            placed = True
                            break
                    else:
                        if d2 <= DOT_R * DOT_R:
                            r, g, b = ORANGE
                            placed = True
                            break
                if placed:
                    break

        row += bytes([r, g, b, a])
    rows.append(bytes(row))

# ── Write PNG ────────────────────────────────────────────────────────────────

def png_chunk(tag, data):
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


raw = b"".join(rows)
compressed = zlib.compress(raw, level=9)

ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)   # bit depth 8, RGBA

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
with open(out, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n")
    f.write(png_chunk(b"IHDR", ihdr))
    f.write(png_chunk(b"IDAT", compressed))
    f.write(png_chunk(b"IEND", b""))

print(f"Written: {out}")
