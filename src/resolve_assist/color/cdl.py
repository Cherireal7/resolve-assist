"""ASC-CDL math, matching how Resolve applies a CDL on a node.

Order per channel: out = clamp(in * slope + offset, 0, 1) ** power,
then saturation around Rec.709 luma. All values are display-referred 0..1.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

RGB = tuple[float, float, float]

# Rec.709 / sRGB luma weights (ASC-CDL v1.2 saturation spec).
LUMA_R, LUMA_G, LUMA_B = 0.2126, 0.7152, 0.0722

# Safety limits: values outside these are almost certainly a mistake.
SLOPE_RANGE = (0.0, 4.0)
OFFSET_RANGE = (-1.0, 1.0)
POWER_RANGE = (0.1, 4.0)
SAT_RANGE = (0.0, 4.0)


def luma(r: float, g: float, b: float) -> float:
    return LUMA_R * r + LUMA_G * g + LUMA_B * b


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _triple(value: float | Sequence[float] | str, name: str) -> RGB:
    """Accept 1.1, [1.1, 1.0, 0.9] or "1.1 1.0 0.9"."""
    if isinstance(value, str):
        parts = [float(p) for p in value.replace(",", " ").split()]
        value = parts[0] if len(parts) == 1 else parts  # "0.1" means 0.1 for all channels
    if isinstance(value, (int, float)):
        v = float(value)
        return (v, v, v)
    items = [float(v) for v in value]
    if len(items) != 3:
        raise ValueError(f"{name} needs 1 or 3 numbers, got {len(items)}")
    return (items[0], items[1], items[2])


@dataclass(frozen=True)
class CDL:
    slope: RGB = (1.0, 1.0, 1.0)
    offset: RGB = (0.0, 0.0, 0.0)
    power: RGB = (1.0, 1.0, 1.0)
    saturation: float = 1.0
    notes: tuple[str, ...] = field(default=(), compare=False)

    @classmethod
    def make(
        cls,
        slope: float | Sequence[float] | str = 1.0,
        offset: float | Sequence[float] | str = 0.0,
        power: float | Sequence[float] | str = 1.0,
        saturation: float = 1.0,
        notes: Iterable[str] = (),
    ) -> "CDL":
        cdl = cls(
            _triple(slope, "slope"),
            _triple(offset, "offset"),
            _triple(power, "power"),
            float(saturation),
            tuple(notes),
        )
        cdl.validate()
        return cdl

    def validate(self) -> None:
        checks = (
            ("slope", self.slope, SLOPE_RANGE),
            ("offset", self.offset, OFFSET_RANGE),
            ("power", self.power, POWER_RANGE),
        )
        for name, values, (lo, hi) in checks:
            for v in values:
                if not (lo <= v <= hi) or v != v:  # v != v catches NaN
                    raise ValueError(f"{name} value {v} outside safe range {lo}..{hi}")
        lo, hi = SAT_RANGE
        if not (lo <= self.saturation <= hi):
            raise ValueError(f"saturation {self.saturation} outside safe range {lo}..{hi}")

    def is_identity(self) -> bool:
        return self == CDL()

    def apply(self, rgb: RGB) -> RGB:
        out = []
        for c in range(3):
            v = _clamp(rgb[c] * self.slope[c] + self.offset[c])
            out.append(v ** self.power[c] if v > 0.0 else 0.0)
        r, g, b = out
        if self.saturation != 1.0:
            y = luma(r, g, b)
            s = self.saturation
            r, g, b = (_clamp(y + s * (r - y)), _clamp(y + s * (g - y)), _clamp(y + s * (b - y)))
        return (r, g, b)

    def blend(self, strength: float) -> "CDL":
        """Interpolate toward identity: 0 = no change, 1 = full effect."""
        t = _clamp(strength, 0.0, 2.0)

        def mix(a: RGB, ident: float) -> RGB:
            return tuple(ident + (x - ident) * t for x in a)  # type: ignore[return-value]

        return CDL(
            mix(self.slope, 1.0),
            mix(self.offset, 0.0),
            mix(self.power, 1.0),
            1.0 + (self.saturation - 1.0) * t,
            self.notes,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notes"] = list(self.notes)
        d["resolve"] = self.resolve_strings()
        return d

    def resolve_strings(self) -> dict[str, str]:
        """Strings in the shape Resolve's SetCDL() and the CDL panel expect."""

        def fmt(t: RGB) -> str:
            return " ".join(f"{v:.4f}" for v in t)

        return {
            "Slope": fmt(self.slope),
            "Offset": fmt(self.offset),
            "Power": fmt(self.power),
            "Saturation": f"{self.saturation:.4f}",
        }

    def to_cc_xml(self, cc_id: str = "resolve-assist") -> str:
        """ASC .cc file, importable by most grading tools."""
        s = self.resolve_strings()
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ColorCorrection id="{cc_id}">\n'
            "  <SOPNode>\n"
            f"    <Slope>{s['Slope']}</Slope>\n"
            f"    <Offset>{s['Offset']}</Offset>\n"
            f"    <Power>{s['Power']}</Power>\n"
            "  </SOPNode>\n"
            "  <SatNode>\n"
            f"    <Saturation>{s['Saturation']}</Saturation>\n"
            "  </SatNode>\n"
            "</ColorCorrection>\n"
        )
