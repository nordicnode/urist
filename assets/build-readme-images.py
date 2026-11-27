#!/usr/bin/env python3
"""Render README headings with Kruggsmash's tileset glyphs.

The tileset is a 16x16 CP437 grid (180px tiles, white/grey glyphs on
magenta, the DF transparent colour). Text is rendered in capitals with
the tileset's own letter glyphs, on Kruggsmash's black (21,19,15),
composed at full tile size and downscaled by an integer factor with
nearest-neighbour so the glyphs stay crisp. Usage:

    python3 assets/build-readme-images.py          # all headings
    python3 assets/build-readme-images.py "WHAT IT IS"   # one test

Heading images land in assets/headings/<slug>.png.
"""
import os
import sys

from PIL import Image
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "kruggsmash-tileset.png")
OUT_DIR = os.path.join(HERE, "headings")

TILE = 180
FACTOR = 6          # 180px tile -> 30px letters
GAP = 15            # px between glyphs at full scale
PAD_X = 90          # px horizontal padding at full scale
PAD_Y = 45          # px vertical padding at full scale
MAGENTA = np.array([255, 0, 255], dtype=np.uint8)
BG = (21, 19, 15)   # Kruggsmash BLACK_R/G/B

HEADINGS = [
    "What it is",
    "Status",
    "How it works",
    "The diary",
    "More systems",
    "Design principles",
    "Quickstart",
    "The agent protocol",
    "Project layout",
    "Roadmap",
    "Set it up with your AI",
    "License",
    "Links",
]

sheet = np.array(Image.open(SRC).convert("RGB"))


def glyph(code):
    r, c = divmod(code, 16)
    return sheet[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE]


def render_codes(codes):
    """Render a list of CP437 glyph codes to an RGB image."""
    n = len(codes)
    w = PAD_X * 2 + n * TILE + (n - 1) * GAP
    h = TILE + PAD_Y * 2
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:, :] = BG
    x = PAD_X
    for code in codes:
        if code is not None:
            tile = glyph(code)
            mask = np.any(tile != MAGENTA, axis=2)
            region = canvas[PAD_Y:PAD_Y + TILE, x:x + TILE]
            region[mask] = tile[mask]
        x += TILE + GAP
    img = Image.fromarray(canvas)
    img = img.resize((w // FACTOR, h // FACTOR), Image.NEAREST)
    return img


def render(text):
    """Render text (capitals) to an RGB array at full tile scale."""
    return render_codes([ord(c) if c != " " else None for c in text.upper()])


def slug(text):
    return text.lower().replace(" ", "-")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = sys.argv[1:] or HEADINGS
    for text in targets:
        if text == "divider":
            # ═ (0xCD) line with the dwarf face (0x01) in the middle.
            img = render_codes([0xCD] * 10 + [0x01] + [0xCD] * 10)
            path = os.path.join(OUT_DIR, "divider.png")
        else:
            img = render(text)
            path = os.path.join(OUT_DIR, slug(text) + ".png")
        img.save(path)
        print(f"{path}  {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
