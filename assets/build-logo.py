#!/usr/bin/env python3
"""Urist logo from Kruggsmash's tileset: proper glyphs, not hand-drawn.

Source: Kruggsmash's tileset (https://i.imgur.com/SVAmWwD.png, from his
video description), a 16x16 CP437 tileset, 180px tiles, white/grey
glyphs on magenta (the DF transparent colour). The dwarf face is glyph
0x01 (the classic DF dwarf smiley); the wordmark uses the tileset's
own letter glyphs. Background is Kruggsmash's black (21,19,15) from
his colours.txt. Magenta is treated as transparent everywhere.
Nearest-neighbour scaling only, so the glyphs stay crisp.

Run with system python3 (needs PIL + numpy; the repo venv has
neither). The tileset is fetched from the URL below when it is not
already at SRC, so the logo is reproducible from a clean checkout.
"""
from pathlib import Path
import urllib.request

from PIL import Image
import numpy as np

# The tileset lives in the repo now (committed with the README
# glyphs, 2026-11-27); fetch from the URL only if it is missing.
SRC = Path(__file__).resolve().parent / "kruggsmash-tileset.png"
SRC_URL = "https://i.imgur.com/SVAmWwD.png"
OUT = Path(__file__).resolve().parent / "logo.png"

TILE = 180
MAGENTA = np.array([255, 0, 255], dtype=np.uint8)
BG = (21, 19, 15)  # Kruggsmash BLACK_R/G/B

if not Path(SRC).exists():
    print("fetching tileset from", SRC_URL)
    urllib.request.urlretrieve(SRC_URL, SRC)
sheet = np.array(Image.open(SRC).convert("RGB"))

def glyph(code):
    r, c = divmod(code, 16)
    return sheet[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE]

def paste(canvas, tile, scale, x0, y0):
    """Paste a tileset glyph onto the canvas, magenta as transparent."""
    h, w, _ = tile.shape
    big = np.array(Image.fromarray(tile).resize(
        (w * scale, h * scale), Image.NEAREST))
    mask = np.any(big != MAGENTA, axis=2)
    region = canvas[y0:y0 + big.shape[0], x0:x0 + big.shape[1]]
    region[mask] = big[mask]

canvas = np.zeros((1600, 1600, 3), dtype=np.uint8)
canvas[:, :] = BG

# Dwarf face, glyph 0x01, 5x -> 900px, vertically centred with the wordmark.
FACE_SCALE = 5
face_w = TILE * FACE_SCALE
face_x = (1600 - face_w) // 2
face_y = 200
paste(canvas, glyph(0x01), FACE_SCALE, face_x, face_y)

# Wordmark URIST, tileset letters at 1x, 12px gaps.
LETTER_GAP = 12
word_w = 5 * TILE + 4 * LETTER_GAP
x = (1600 - word_w) // 2
y = face_y + face_w + 120
for ch in "URIST":
    paste(canvas, glyph(ord(ch)), 1, x, y)
    x += TILE + LETTER_GAP

Image.fromarray(canvas).save(OUT)
print("saved", OUT)
