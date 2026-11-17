"""Overlay and background images generated from scratch (free to use).

Blend-mode hints (Resolve Inspector → Composite Mode):
- light leaks, bokeh, dust: black background → "Screen" or "Add"
- grain: mid-gray → "Overlay"
- vignette, letterbox, lower-third panel: transparent PNG → "Normal"
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from ..imaging.png import encode_png


def _save(path: Path, w: int, h: int, px: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(w, h, px))


def light_leak(path: Path, w: int, h: int, seed: int, palette: list[tuple[float, float, float]]) -> None:
    rnd = random.Random(seed)
    blobs = []
    for _ in range(3):
        edge = rnd.choice(["left", "right", "top", "corner"])
        cx = {"left": -0.1, "right": 1.1, "top": rnd.uniform(0.2, 0.8), "corner": rnd.choice([-0.05, 1.05])}[edge]
        cy = {"left": rnd.uniform(0.1, 0.9), "right": rnd.uniform(0.1, 0.9), "top": -0.1, "corner": rnd.choice([-0.05, 1.05])}[edge]
        blobs.append((cx, cy, rnd.uniform(0.25, 0.6), rnd.choice(palette), rnd.uniform(0.6, 1.0)))
    px = []
    for y in range(h):
        v = y / h
        for x in range(w):
            u = x / w
            r = g = b = 0.0
            for cx, cy, rad, col, k in blobs:
                d2 = ((u - cx) ** 2 + ((v - cy) * h / w) ** 2) / (rad * rad)
                a = k * math.exp(-d2 * 2.2)
                r += col[0] * a
                g += col[1] * a
                b += col[2] * a
            px.append((r, g, b))
    _save(path, w, h, px)


def bokeh(path: Path, w: int, h: int, seed: int, tint: tuple[float, float, float]) -> None:
    rnd = random.Random(seed)
    img = [[0.0, 0.0, 0.0] for _ in range(w * h)]
    for _ in range(28):
        cx, cy = rnd.uniform(0, w), rnd.uniform(0, h)
        rad = rnd.uniform(0.02, 0.07) * w
        col = tuple(min(1.0, t * rnd.uniform(0.7, 1.2)) for t in tint)
        k = rnd.uniform(0.15, 0.45)
        x0, x1 = max(0, int(cx - rad - 2)), min(w, int(cx + rad + 2))
        y0, y1 = max(0, int(cy - rad - 2)), min(h, int(cy + rad + 2))
        for y in range(y0, y1):
            for x in range(x0, x1):
                d = math.hypot(x - cx, y - cy) / rad
                if d < 1.05:
                    edge = 1.0 + 0.4 * max(0.0, d - 0.85) / 0.15 if d < 1.0 else (1.05 - d) / 0.05
                    a = k * min(1.0, edge)
                    p = img[y * w + x]
                    for c in range(3):
                        p[c] = min(1.0, p[c] + col[c] * a)
    _save(path, w, h, [tuple(p) for p in img])


def vignette(path: Path, w: int, h: int, strength: float) -> None:
    px = []
    for y in range(h):
        for x in range(w):
            u, v = (x / w - 0.5) * 2, (y / h - 0.5) * 2
            d = math.sqrt(u * u * 0.8 + v * v * 1.0)
            a = max(0.0, min(1.0, (d - 0.55) / 0.9)) ** 1.6 * strength
            px.append((0.0, 0.0, 0.0, a))
    _save(path, w, h, px)


def grain(path: Path, w: int, h: int, seed: int, amount: float) -> None:
    rnd = random.Random(seed)
    px = []
    for _ in range(w * h):
        v = 0.5 + rnd.gauss(0, amount)
        px.append((v, v, v))
    _save(path, w, h, px)


def dust(path: Path, w: int, h: int, seed: int) -> None:
    rnd = random.Random(seed)
    img = [0.0] * (w * h)
    for _ in range(int(w * h / 2500)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r = rnd.choice([1, 1, 1, 2, 3])
        v = rnd.uniform(0.3, 0.9)
        for yy in range(max(0, y - r), min(h, y + r + 1)):
            for xx in range(max(0, x - r), min(w, x + r + 1)):
                if (xx - x) ** 2 + (yy - y) ** 2 <= r * r:
                    img[yy * w + xx] = max(img[yy * w + xx], v)
    for _ in range(4):  # vertical scratches
        x = rnd.randrange(w)
        y0, y1 = sorted((rnd.randrange(h), rnd.randrange(h)))
        for y in range(y0, y1):
            img[y * w + x] = max(img[y * w + x], rnd.uniform(0.3, 0.7))
    _save(path, w, h, [(v, v, v) for v in img])


def letterbox(path: Path, w: int, h: int, ratio: float) -> None:
    bar = max(0, int((h - w / ratio) / 2))
    px = [(0.0, 0.0, 0.0, 1.0 if (y < bar or y >= h - bar) else 0.0) for y in range(h) for _ in range(w)]
    _save(path, w, h, px)


def gradient(path: Path, w: int, h: int, c1, c2, angle_deg: float = 35.0) -> None:
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    span = abs(dx * w) + abs(dy * h)
    px = []
    for y in range(h):
        for x in range(w):
            t = ((x * dx + y * dy) - min(0, dx * w) - min(0, dy * h)) / span
            t = t * t * (3 - 2 * t)  # smoothstep
            px.append(tuple(c1[i] + (c2[i] - c1[i]) * t for i in range(3)))
    _save(path, w, h, px)


def lower_third(path: Path, w: int, h: int, accent) -> None:
    """Transparent 1920x1080 frame with a soft dark panel bottom-left and an accent line."""
    x0, x1 = int(w * 0.06), int(w * 0.52)
    y0, y1 = int(h * 0.76), int(h * 0.90)
    px = []
    for y in range(h):
        for x in range(w):
            if x0 <= x <= x1 and y0 <= y <= y1:
                fade = min(1.0, (x1 - x) / (w * 0.08))
                if x - x0 < 8:
                    px.append((accent[0], accent[1], accent[2], 1.0))
                else:
                    px.append((0.05, 0.05, 0.07, 0.72 * fade))
            else:
                px.append((0.0, 0.0, 0.0, 0.0))
    _save(path, w, h, px)
