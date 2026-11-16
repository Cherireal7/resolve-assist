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


def analyze_image(img: Image, decoder: str = "") -> Stats:
    core = analyze_pixels(img.pixels)
    used_neutral = core.pop("used_neutral")
    stats = Stats(
        width=img.width,
        height=img.height,
        source_width=img.source_width,
        source_height=img.source_height,
        samples=len(img.pixels),
        decoder=decoder,
        **core,
    )
    _assess(stats, used_neutral)
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
