"""Visual fingerprints of a frame: what a match cut can rhyme on.

All features work on small thumbnails (e.g. 160 px wide) with stdlib math:
- layout: 16x9 grid of mean luma (where bright and dark masses sit)
- edges: 8-bin histogram of gradient orientation, weighted by strength (lines, shapes)
- colors: 3 dominant colors (tiny k-means) with their share
- centroid: brightness-weighted center of mass (where the eye goes)
- sharpness: gradient energy (pick the best frame of a shot)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..color.cdl import RGB, luma
from ..imaging.png import Image

GRID_W, GRID_H = 16, 9


@dataclass
class Fingerprint:
    layout: list[float]                     # GRID_W * GRID_H mean luma, row-major
    edges: list[float]                      # 8 bins, sums to 1 (or zeros for flat frames)
    colors: list[tuple[RGB, float]]         # dominant colors with share
    centroid: tuple[float, float]           # 0..1, (x, y) with y down
    sharpness: float
    mean_luma: float
    extra: dict = field(default_factory=dict)


def _gray(img: Image) -> list[float]:
    return [luma(*p) for p in img.pixels]


def fingerprint(img: Image) -> Fingerprint:
    w, h = img.width, img.height
    if w < 4 or h < 4:
        raise ValueError("frame too small to fingerprint")
    g = _gray(img)

    # layout grid
    sums = [0.0] * (GRID_W * GRID_H)
    counts = [0] * (GRID_W * GRID_H)
    for y in range(h):
        gy = min(GRID_H - 1, y * GRID_H // h)
        row = y * w
        for x in range(w):
            gx = min(GRID_W - 1, x * GRID_W // w)
            k = gy * GRID_W + gx
            sums[k] += g[row + x]
            counts[k] += 1
    layout = [s / c if c else 0.0 for s, c in zip(sums, counts)]

    # gradients: orientation histogram + sharpness
    hist = [0.0] * 8
    energy = 0.0
    for y in range(1, h - 1):
        row = y * w
        for x in range(1, w - 1):
            gx = g[row + x + 1] - g[row + x - 1]
            gy = g[row + w + x] - g[row - w + x]
            m = math.hypot(gx, gy)
            if m < 0.02:
                continue
            energy += m * m
            ang = math.atan2(gy, gx) % math.pi          # orientation, not direction
            hist[min(7, int(ang / math.pi * 8))] += m
    total = sum(hist)
    edges = [v / total for v in hist] if total else [0.0] * 8
    sharpness = energy / ((w - 2) * (h - 2))

    # brightness centroid
    tw = sum(g) or 1e-9
    cx = sum(g[y * w + x] * x for y in range(h) for x in range(w)) / tw / (w - 1)
    cy = sum(g[y * w + x] * y for y in range(h) for x in range(w)) / tw / (h - 1)

    return Fingerprint(layout, edges, _dominant_colors(img.pixels), (cx, cy), sharpness, sum(g) / len(g))


def _dominant_colors(pixels: list[RGB], k: int = 3, iters: int = 8) -> list[tuple[RGB, float]]:
    step = max(1, len(pixels) // 2000)
    pts = pixels[::step]
    # deterministic init: darkest, median, brightest by luma
    srt = sorted(pts, key=lambda p: luma(*p))
    centers = [srt[0], srt[len(srt) // 2], srt[-1]][:k]
    assign = [0] * len(pts)
    for _ in range(iters):
        for i, p in enumerate(pts):
            assign[i] = min(range(len(centers)), key=lambda c: sum((p[j] - centers[c][j]) ** 2 for j in range(3)))
        new = []
        for c in range(len(centers)):
            members = [pts[i] for i in range(len(pts)) if assign[i] == c]
            new.append(tuple(sum(m[j] for m in members) / len(members) for j in range(3)) if members else centers[c])
        centers = new
    shares = [assign.count(c) / len(pts) for c in range(len(centers))]
    return sorted(zip(centers, shares), key=lambda cs: -cs[1])  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- similarity

def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va < 1e-9 or vb < 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def similarity(a: Fingerprint, b: Fingerprint) -> dict[str, float]:
    """Per-aspect similarity 0..1 plus a weighted total."""
    layout = max(0.0, _corr(a.layout, b.layout))
    edges = sum(min(x, y) for x, y in zip(a.edges, b.edges)) if sum(a.edges) and sum(b.edges) else 0.0
    color = 0.0
    for ca, sa in a.colors:
        best = min(math.dist(ca, cb) for cb, _ in b.colors)
        color += sa * max(0.0, 1.0 - best / 0.5)
    pos = max(0.0, 1.0 - math.dist(a.centroid, b.centroid) / 0.5)
    total = 0.40 * layout + 0.25 * edges + 0.15 * color + 0.20 * pos
    return {"total": total, "layout": layout, "shape": edges, "color": color, "position": pos}
