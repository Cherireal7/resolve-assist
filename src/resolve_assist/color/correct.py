"""Turn measurements into corrections: auto balance and shot matching."""

from __future__ import annotations

from ..analyze import MID_GRAY_TARGET, Stats, analyze_pixels
from .cdl import CDL, RGB

MAX_SLOPE_STEP = (0.5, 2.5)
MAX_EXPOSURE_GAIN = (0.5, 2.0)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def auto_balance(stats: Stats, fix_exposure: bool = True, fix_blacks: bool = True) -> CDL:
    """Neutralize cast, normalize mid-tones and set the black point.

    White balance: scale channels so the neutral mean becomes gray (keeps its luma).
    Exposure: scale so median luma lands near MID_GRAY_TARGET (clamped, gentle).
    Blacks: small offset so the 1st percentile sits just above 0.
    """
    nm = stats.neutral_mean
    gray = sum(nm) / 3
    notes: list[str] = []
    wb = [gray / c if c > 1e-4 else 1.0 for c in nm]
    # Normalize so green stays ~1: avoids shifting brightness through WB alone.
    wb = [v / wb[1] for v in wb]

    exposure = 1.0
    if fix_exposure and stats.luma.p50 > 1e-3:
        exposure = _clamp(MID_GRAY_TARGET / stats.luma.p50, *MAX_EXPOSURE_GAIN)
        # Don't push highlights into clipping: limit by the 99th percentile.
        if exposure > 1.0 and stats.luma.p99 * exposure > 0.98:
            # Brightening would clip: brighten only as far as the highlights allow.
            exposure = max(1.0, 0.98 / max(stats.luma.p99, 1e-3))
            notes.append("exposure gain limited to protect highlights")
    slope = tuple(_clamp(w * exposure, *MAX_SLOPE_STEP) for w in wb)

    offset_v = 0.0
    if fix_blacks:
        black = stats.luma.p01 * (sum(slope) / 3)
        offset_v = _clamp(0.01 - black, -0.08, 0.03)
    offset = (offset_v, offset_v, offset_v)

    cast = ", ".join(f"{k} {v * 100:+.1f}%" for k, v in stats.cast.items())
    notes.insert(0, f"measured cast: {cast}")
    notes.append(f"exposure gain {exposure:.2f}, black offset {offset_v:+.3f}")
    if stats.confidence < 0.6:
        notes.append(f"low confidence ({stats.confidence:.2f}); check visually before applying")
    return CDL.make(slope=slope, offset=offset, power=1.0, saturation=1.0, notes=notes)


def match_shot(source: Stats, reference: Stats, strength: float = 1.0) -> CDL:
    """Make `source` look like `reference`: per channel mean/contrast transfer.

    out = in * (ref_std / src_std) + (ref_mean - slope * src_mean)
    """
    slope = []
    offset = []
    for ch in ("red", "green", "blue"):
        s, r = getattr(source, ch), getattr(reference, ch)
        k = _clamp(r.std / s.std if s.std > 1e-4 else 1.0, *MAX_SLOPE_STEP)
        slope.append(k)
        offset.append(_clamp(r.mean - k * s.mean, -0.3, 0.3))
    sat = 1.0
    if source.saturation_mean > 1e-3:
        # Slope already scales chroma; correct the remainder.
        avg_k = sum(slope) / 3
        sat = _clamp(reference.saturation_mean / (source.saturation_mean * avg_k), 0.5, 1.6)
    notes = [
        f"matched per-channel mean/contrast to reference (strength {strength:.2f})",
        "check skin tones visually; matching is statistical, not semantic",
    ]
    if min(source.confidence, reference.confidence) < 0.6:
        notes.append("low confidence on one of the frames")
    return CDL.make(slope=slope, offset=offset, power=1.0, saturation=sat, notes=notes).blend(strength)


def verify(cdl: CDL, pixels: list[RGB]) -> dict:
    """Re-measure after applying the CDL, so the AI can report real results."""
    after = analyze_pixels([cdl.apply(p) for p in pixels])
    return {
        "cast_after": {k: round(v, 4) for k, v in after["cast"].items()},
        "median_luma_after": round(after["luma"].p50, 4),
        "clip_white_pct_after": round(after["clip_white_pct"], 3),
        "clip_black_pct_after": round(after["clip_black_pct"], 3),
    }
