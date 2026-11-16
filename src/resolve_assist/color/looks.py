"""Starter look library: a CDL + tone curve + split toning, with strength control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .cdl import CDL, RGB, luma

Transform = Callable[[RGB], RGB]


@dataclass(frozen=True)
class Look:
    name: str
    description: str
    cdl: CDL
    contrast: float = 0.0             # S-curve amount around the pivot, -0.5..0.8
    pivot: float = 0.435
    shadow_tint: RGB = (0.0, 0.0, 0.0)     # added to shadows (luma-weighted)
    highlight_tint: RGB = (0.0, 0.0, 0.0)  # added to highlights
    black_lift: float = 0.0           # milky/faded blacks


LOOKS: dict[str, Look] = {
    look.name: look
    for look in (
        Look("warm-film", "Warm, soft film print: gentle S-curve, lifted blacks, golden highlights",
             CDL.make(slope=(1.04, 1.0, 0.94), power=(0.98, 1.0, 1.03), saturation=0.92),
             contrast=0.25, highlight_tint=(0.02, 0.01, -0.015), black_lift=0.025),
        Look("teal-orange", "Blockbuster complementary look: teal shadows, warm skin and highlights",
             CDL.make(saturation=1.08),
             contrast=0.3, shadow_tint=(-0.03, 0.01, 0.035), highlight_tint=(0.03, 0.008, -0.03)),
        Look("cool-night", "Cool, moody night: blue shadows, lowered exposure, reduced saturation",
             CDL.make(slope=(0.9, 0.95, 1.05), offset=-0.01, saturation=0.8),
             contrast=0.2, shadow_tint=(-0.01, 0.0, 0.03)),
        Look("bleach-bypass", "Silver-retained look: high contrast, desaturated, gritty",
             CDL.make(saturation=0.55), contrast=0.55),
        Look("clean-commercial", "Bright, clean and punchy, neutral whites",
             CDL.make(slope=1.03, saturation=1.12), contrast=0.15),
        Look("bw-contrast", "Black & white with a rich contrast curve",
             CDL.make(saturation=0.0), contrast=0.35),
    )
}


def _s_curve(v: float, amount: float, pivot: float) -> float:
    """Smooth, monotonic contrast curve that keeps 0, pivot and 1 fixed."""
    if amount == 0.0:
        return v
    if v <= pivot:
        x = v / pivot
        y = x ** (1.0 + amount)
        return y * pivot
    x = (v - pivot) / (1.0 - pivot)
    y = 1.0 - (1.0 - x) ** (1.0 + amount)
    return pivot + y * (1.0 - pivot)


def look_transform(look: Look, strength: float = 1.0, base: CDL | None = None) -> Transform:
    """Build the full pixel transform: optional correction first, then the look."""
    t = max(0.0, min(2.0, strength))
    cdl = look.cdl.blend(t)
    contrast = look.contrast * t
    sh = tuple(v * t for v in look.shadow_tint)
    hi = tuple(v * t for v in look.highlight_tint)
    lift = look.black_lift * t

    def fn(rgb: RGB) -> RGB:
        if base is not None:
            rgb = base.apply(rgb)
        r, g, b = cdl.apply(rgb)
        y = luma(r, g, b)
        ws = (1.0 - y) ** 2
        wh = y ** 2
        out = []
        for i, v in enumerate((r, g, b)):
            v = _s_curve(v, contrast, look.pivot) if contrast > 0 else v
            v = v + sh[i] * ws + hi[i] * wh
            v = lift + v * (1.0 - lift)
            out.append(min(1.0, max(0.0, v)))
        return (out[0], out[1], out[2])

    return fn


def cdl_transform(cdl: CDL) -> Transform:
    return cdl.apply


def list_looks() -> list[dict]:
    return [{"name": k, "description": v.description} for k, v in LOOKS.items()]
