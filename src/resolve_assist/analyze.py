"""Image statistics a colorist looks at: exposure, contrast, cast, clipping."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .color.cdl import RGB, luma
from .imaging.png import Image

MID_GRAY_TARGET = 0.42      # Rec.709 display mid gray-ish for a "normal" exposure
NEUTRAL_MAX_CHROMA = 0.12   # pixels this close to gray vote for white balance
NEUTRAL_LUMA = (0.12, 0.92)


@dataclass
class ChannelStats:
    mean: float
    std: float
    p01: float
    p50: float
    p99: float


@dataclass
class Stats:
    width: int
    height: int
    source_width: int
    source_height: int
    samples: int
    red: ChannelStats
    green: ChannelStats
    blue: ChannelStats
    luma: ChannelStats
    saturation_mean: float
    clip_black_pct: float
    clip_white_pct: float
    neutral_pixels_pct: float
    neutral_mean: RGB           # mean of near-gray pixels (or all pixels when too few)
    cast: dict[str, float]      # per channel deviation from neutral, e.g. {"red": +0.04}
    luma_histogram: list[float]  # 16 bins, fractions
    warnings: list[str] = field(default_factory=list)
    confidence: float = 1.0
    decoder: str = ""
    borders: dict | None = None  # letterbox/pillarbox bars that were excluded

    def to_dict(self) -> dict:
        d = asdict(self)
        return _round(d)


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    return obj


def _channel(values: list[float]) -> ChannelStats:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    s = sorted(values)

    def pct(p: float) -> float:
        return s[min(n - 1, int(p * (n - 1) + 0.5))]

    return ChannelStats(mean, math.sqrt(var), pct(0.01), pct(0.5), pct(0.99))


def analyze_pixels(pixels: list[RGB]) -> dict:
    """Core math on raw pixels; returns the pieces used by Stats and correct.py."""
    if not pixels:
        raise ValueError("image has no pixels")
    rs = [p[0] for p in pixels]
    gs = [p[1] for p in pixels]
    bs = [p[2] for p in pixels]
    ys = [luma(*p) for p in pixels]
    sat = [max(p) - min(p) for p in pixels]
    n = len(pixels)

    neutral = [p for p, c, y in zip(pixels, sat, ys) if c < NEUTRAL_MAX_CHROMA and NEUTRAL_LUMA[0] < y < NEUTRAL_LUMA[1]]
    source = neutral if len(neutral) >= max(50, n // 50) else pixels
    nm = tuple(sum(p[i] for p in source) / len(source) for i in range(3))
    gray = sum(nm) / 3 or 1e-6
    cast = {name: (nm[i] - gray) / gray for i, name in enumerate(("red", "green", "blue"))}

    hist = [0] * 16
    for y in ys:
        hist[min(15, int(y * 16))] += 1

    return {
        "red": _channel(rs),
        "green": _channel(gs),
        "blue": _channel(bs),
        "luma": _channel(ys),
        "saturation_mean": sum(sat) / n,
        "clip_black_pct": 100 * sum(1 for y in ys if y <= 0.004) / n,
        "clip_white_pct": 100 * sum(1 for p in pixels if max(p) >= 0.996) / n,
        "neutral_pixels_pct": 100 * len(neutral) / n,
        "neutral_mean": nm,
        "used_neutral": source is neutral,
        "cast": cast,
        "luma_histogram": [h / n for h in hist],
    }


BORDER_MAX = 0.02  # a row/column whose brightest pixel is below this counts as a black bar


def crop_borders(img: Image) -> tuple[Image, dict | None]:
    """Remove letterbox/pillarbox bars (e.g. vertical phone video in a 16:9 timeline).

    Bars must be near-black across the whole row/column and touch an edge.
    Returns the cropped image and a description, or the original and None.
    """
    w, h, px = img.width, img.height, img.pixels

    def col_dark(x: int) -> bool:
        return all(max(px[y * w + x]) < BORDER_MAX for y in range(h))

    def row_dark(y: int) -> bool:
        return all(max(p) < BORDER_MAX for p in px[y * w:(y + 1) * w])

    left = 0
    while left < w - 1 and col_dark(left):
        left += 1
    right = w - 1
    while right > left and col_dark(right):
        right -= 1
    top = 0
    while top < h - 1 and row_dark(top):
        top += 1
    bottom = h - 1
    while bottom > top and row_dark(bottom):
        bottom -= 1
    cw, ch = right - left + 1, bottom - top + 1
    # Ignore tiny trims (noise) and refuse to crop to almost nothing (a dark scene, not bars).
    if (cw == w and ch == h) or cw * ch < 0.1 * w * h or (w - cw < 0.02 * w and h - ch < 0.02 * h):
        return img, None
    cropped = [px[y * w + x] for y in range(top, bottom + 1) for x in range(left, right + 1)]
    sx = img.source_width / w if img.source_width else 1.0
    sy = img.source_height / h if img.source_height else 1.0
    info = {
        "kind": "pillarbox" if cw < w and ch == h else "letterbox" if ch < h and cw == w else "windowbox",
        "removed_pct": round(100 * (1 - cw * ch / (w * h)), 1),
        "picture_size_estimate": [round(cw * sx), round(ch * sy)],
        "box": [left, top, right, bottom],
    }
    return Image(cw, ch, cropped, img.source_width, img.source_height), info


def analyze_image(img: Image, decoder: str = "", crop: bool = True, border: dict | None = None) -> Stats:
    """Measure an image. With crop=True black bars are removed first; callers that
    already cropped (to reuse the cropped pixels) pass crop=False and the border info."""
    if crop:
        img, border = crop_borders(img)
    core = analyze_pixels(img.pixels)
    used_neutral = core.pop("used_neutral")
    stats = Stats(
        width=img.width,
        height=img.height,
        source_width=img.source_width,
        source_height=img.source_height,
        samples=len(img.pixels),
        decoder=decoder,
        borders=border,
        **core,
    )
    _assess(stats, used_neutral)
    if border:
        stats.warnings.insert(0, f"ignored black bars ({border['kind']}, {border['removed_pct']}% of frame)")
    return stats


def _assess(s: Stats, used_neutral: bool) -> None:
    w = s.warnings
    conf = 1.0
    y = s.luma
    if y.p50 < 0.18:
        w.append("underexposed: median luma is low")
    elif y.p50 > 0.70:
        w.append("bright/overexposed: median luma is high")
    if s.clip_white_pct > 2:
        w.append(f"{s.clip_white_pct:.1f}% of pixels clip to white (highlight detail is gone)")
    if s.clip_black_pct > 5:
        w.append(f"{s.clip_black_pct:.1f}% of pixels crushed to black")
    contrast = y.p99 - y.p01
    if contrast < 0.45 and s.saturation_mean < 0.12 and 0.3 < y.p50 < 0.6:
        w.append("looks like LOG/flat footage: apply a log-to-Rec.709 conversion before grading")
        conf -= 0.35
    elif contrast < 0.4:
        w.append("low contrast")
    max_cast = max(abs(v) for v in s.cast.values())
    if max_cast > 0.04:
        dom = max(s.cast, key=lambda k: s.cast[k])
        w.append(f"color cast toward {dom} ({max_cast * 100:.1f}%)")
    if not used_neutral:
        w.append("few neutral (gray/white) areas: white balance guessed from whole frame (gray-world)")
        conf -= 0.25
    if s.samples < 2000:
        conf -= 0.2
    s.confidence = max(0.0, min(1.0, conf))


def apply_box(img: Image, box: list[int]) -> Image:
    """Crop with a box from crop_borders (same sampling size); used to crop all frames of a video alike."""
    left, top, right, bottom = box
    if right >= img.width or bottom >= img.height:
        return img
    w = img.width
    px = [img.pixels[y * w + x] for y in range(top, bottom + 1) for x in range(left, right + 1)]
    return Image(right - left + 1, bottom - top + 1, px, img.source_width, img.source_height)
