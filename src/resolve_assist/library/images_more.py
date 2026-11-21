"""More generated stills: mesh gradients, textures, patterns and vertical-video helpers (stdlib only)."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Callable

from ..imaging.png import encode_png

RGB = tuple[float, float, float]


def _render(path: Path, w: int, h: int, fn: Callable[[float, float, int, int], tuple]) -> None:
    px = [fn(x / w, y / h, x, y) for y in range(h) for x in range(w)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(w, h, px))


def _lerp(a: RGB, b: RGB, t: float) -> RGB:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def mesh(path: Path, w: int, h: int, colors: list[RGB], seed: int) -> None:
    """Soft multi-colour 'mesh' gradient: each colour pulls on the pixels near its point."""
    rnd = random.Random(seed)
    pts = [(rnd.uniform(0.0, 1.0), rnd.uniform(0.0, 1.0), c) for c in colors]
    asp = h / w

    def fn(u: float, v: float, _x: int, _y: int) -> tuple:
        r = g = b = tot = 0.0
        for cx, cy, c in pts:
            k = 1.0 / (((u - cx) ** 2 + ((v - cy) * asp) ** 2) ** 1.4 + 0.004)
            r, g, b, tot = r + c[0] * k, g + c[1] * k, b + c[2] * k, tot + k
        return (r / tot, g / tot, b / tot)
    _render(path, w, h, fn)


def spotlight(path: Path, w: int, h: int, color: RGB, dark: RGB = (0.02, 0.02, 0.03)) -> None:
    """Studio backdrop: a soft pool of light slightly above the centre."""
    asp = h / w

    def fn(u: float, v: float, _x: int, _y: int) -> tuple:
        d = math.sqrt((u - 0.5) ** 2 + ((v - 0.42) * asp) ** 2)
        return _lerp(color, dark, min(1.0, d / 0.75) ** 1.3)
    _render(path, w, h, fn)


def grainy(path: Path, w: int, h: int, c1: RGB, c2: RGB, seed: int, amount: float = 0.06) -> None:
    """Diagonal gradient with visible film-like grain (the 'noise gradient' look)."""
    rnd = random.Random(seed)

    def fn(u: float, v: float, _x: int, _y: int) -> tuple:
        t = min(1.0, max(0.0, 0.5 * u + 0.5 * v + 0.12 * math.sin(3.0 * u + 4.0 * v)))
        n = rnd.gauss(0.0, amount)
        c = _lerp(c1, c2, t * t * (3 - 2 * t))
        return (c[0] + n, c[1] + n, c[2] + n)
    _render(path, w, h, fn)


def paper(path: Path, w: int, h: int, tint: RGB, seed: int) -> None:
    """Paper / card stock: fine grain, soft blotches and a few fibres."""
    rnd = random.Random(seed)
    blots = [(rnd.random(), rnd.random(), rnd.uniform(0.15, 0.5), rnd.uniform(-0.035, 0.035)) for _ in range(14)]
    fibres = {}
    for _ in range(int(w * h / 9000)):
        x, y, ang = rnd.randrange(w), rnd.randrange(h), rnd.uniform(0, math.pi)
        for k in range(rnd.randint(6, 26)):
            fibres[(int(x + k * math.cos(ang)), int(y + k * math.sin(ang)))] = rnd.uniform(-0.06, 0.03)

    def fn(u: float, v: float, x: int, y: int) -> tuple:
        n = rnd.gauss(0.0, 0.018) + fibres.get((x, y), 0.0)
        for cx, cy, rad, a in blots:
            n += a * math.exp(-((u - cx) ** 2 + (v - cy) ** 2) / (rad * rad))
        return (tint[0] + n, tint[1] + n, tint[2] + n)
    _render(path, w, h, fn)


def halftone(path: Path, w: int, h: int, bg: RGB, dot: RGB, cell: int = 36) -> None:
    """Halftone dots that grow from the top-left to the bottom-right."""
    def fn(u: float, v: float, x: int, y: int) -> tuple:
        dx, dy = (x % cell) - cell / 2, (y % cell) - cell / 2
        rad = cell * 0.5 * (0.15 + 0.8 * (u + v) / 2)
        edge = min(1.0, max(0.0, rad - math.hypot(dx, dy) + 0.5))
        return _lerp(bg, dot, edge)
    _render(path, w, h, fn)


def grid(path: Path, w: int, h: int, bg: RGB, line: RGB, cell: int = 60, dots: bool = False) -> None:
    def fn(_u: float, _v: float, x: int, y: int) -> tuple:
        if dots:
            on = math.hypot((x % cell) - cell / 2, (y % cell) - cell / 2) < 3.2
        else:
            on = x % cell < 2 or y % cell < 2
        return line if on else bg
    _render(path, w, h, fn)


def stripes(path: Path, w: int, h: int, c1: RGB, c2: RGB, width: int = 70) -> None:
    def fn(_u: float, _v: float, x: int, y: int) -> tuple:
        t = ((x + y) / width) % 2.0
        edge = min(1.0, max(0.0, (abs(t - 1.0) - 0.5) * width / 2 + 0.5))
        return _lerp(c1, c2, edge)
    _render(path, w, h, fn)


def sunburst(path: Path, w: int, h: int, c1: RGB, c2: RGB, rays: int = 16) -> None:
    def fn(u: float, v: float, _x: int, _y: int) -> tuple:
        a = math.atan2((v - 0.5) * h, (u - 0.5) * w)
        t = 0.5 + 0.5 * math.sin(a * rays)
        return _lerp(c1, c2, min(1.0, max(0.0, (t - 0.5) * 40 + 0.5)))
    _render(path, w, h, fn)


# ---------------------------------------------------------------- transparent helpers for vertical video

def caption_bar(path: Path, w: int, h: int, top: float = 0.60, bottom: float = 0.74, alpha: float = 0.62) -> None:
    """Soft dark band behind captions (transparent elsewhere)."""
    def fn(_u: float, v: float, _x: int, _y: int) -> tuple:
        if v < top - 0.03 or v > bottom + 0.03:
            return (0.0, 0.0, 0.0, 0.0)
        e = min(1.0, (v - (top - 0.03)) / 0.03, ((bottom + 0.03) - v) / 0.03)
        return (0.0, 0.0, 0.0, alpha * max(0.0, e))
    _render(path, w, h, fn)


def scrim(path: Path, w: int, h: int, where: str = "bottom", alpha: float = 0.75) -> None:
    """Gradient to black at the top or bottom so white text stays readable over footage."""
    def fn(_u: float, v: float, _x: int, _y: int) -> tuple:
        t = (v - 0.55) / 0.45 if where == "bottom" else (0.4 - v) / 0.4
        return (0.0, 0.0, 0.0, alpha * min(1.0, max(0.0, t)) ** 1.4)
    _render(path, w, h, fn)


def safe_zones(path: Path, w: int, h: int) -> None:
    """Guide for 9:16 posts: tinted areas are covered by app UI on TikTok / Reels / Shorts.
    Approximate (top 12%, bottom 22%, right 14%): turn the layer off before export."""
    def fn(u: float, v: float, x: int, y: int) -> tuple:
        if v < 0.12 or v > 0.78 or u > 0.86:
            return (1.0, 0.2, 0.25, 0.28)
        if abs(v - 0.12) * h < 2 or abs(v - 0.78) * h < 2 or abs(u - 0.86) * w < 2 or x in (int(w * 0.06),):
            return (1.0, 1.0, 1.0, 0.8)
        return (0.0, 0.0, 0.0, 0.0)
    _render(path, w, h, fn)


def frame(path: Path, w: int, h: int, color: RGB, border: float = 0.035, radius: float = 0.05) -> None:
    """Transparent window with a rounded coloured border (photo-frame look)."""
    bw, r = border * w, radius * w

    def fn(_u: float, _v: float, x: int, y: int) -> tuple:
        dx = max(bw + r - x, x - (w - bw - r), 0.0)
        dy = max(bw + r - y, y - (h - bw - r), 0.0)
        inside = math.hypot(dx, dy) <= r
        return (0.0, 0.0, 0.0, 0.0) if inside else (color[0], color[1], color[2], 1.0)
    _render(path, w, h, fn)


def scanlines(path: Path, w: int, h: int) -> None:
    """CRT / VHS scan lines (transparent PNG, Normal mode, 30-60 % opacity)."""
    def fn(_u: float, _v: float, _x: int, y: int) -> tuple:
        return (0.0, 0.0, 0.0, 0.45 if y % 4 < 2 else 0.0)
    _render(path, w, h, fn)


MESHES: dict[str, list[RGB]] = {
    "aurora": [(0.1, 0.9, 0.7), (0.3, 0.3, 0.95), (0.75, 0.2, 0.9), (0.05, 0.1, 0.3)],
    "candy": [(1.0, 0.45, 0.7), (1.0, 0.75, 0.4), (0.6, 0.5, 1.0), (1.0, 0.9, 0.85)],
    "ember": [(0.95, 0.15, 0.12), (1.0, 0.5, 0.15), (0.35, 0.03, 0.08), (0.1, 0.02, 0.04)],
    "lagoon": [(0.0, 0.55, 0.65), (0.1, 0.85, 0.75), (0.05, 0.2, 0.45), (0.85, 0.95, 0.8)],
    "dusk": [(0.98, 0.6, 0.45), (0.55, 0.3, 0.7), (0.15, 0.12, 0.4), (1.0, 0.85, 0.6)],
    "forest": [(0.05, 0.3, 0.2), (0.35, 0.65, 0.3), (0.9, 0.85, 0.5), (0.02, 0.12, 0.1)],
    "cream": [(0.98, 0.94, 0.86), (0.95, 0.82, 0.72), (0.9, 0.9, 0.8), (1.0, 0.98, 0.94)],
    "midnight": [(0.03, 0.04, 0.12), (0.12, 0.1, 0.35), (0.02, 0.2, 0.3), (0.0, 0.0, 0.03)],
}
GRAINY = {
    "coral": ((1.0, 0.5, 0.4), (0.55, 0.15, 0.45)), "sky": ((0.55, 0.8, 1.0), (0.2, 0.3, 0.75)),
    "lime": ((0.85, 0.95, 0.4), (0.15, 0.55, 0.4)), "charcoal": ((0.22, 0.22, 0.25), (0.05, 0.05, 0.06)),
    "sand": ((0.95, 0.86, 0.7), (0.75, 0.55, 0.4)), "violet": ((0.75, 0.55, 1.0), (0.2, 0.1, 0.45)),
}
SPOTS = {"red": (0.85, 0.12, 0.14), "blue": (0.15, 0.35, 0.85), "teal": (0.1, 0.6, 0.6), "gray": (0.5, 0.5, 0.52),
         "pink": (0.95, 0.5, 0.65), "amber": (0.95, 0.65, 0.2)}
