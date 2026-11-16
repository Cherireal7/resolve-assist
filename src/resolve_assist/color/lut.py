"""Read, write and validate 3D `.cube` LUTs (Adobe/Resolve format)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from .cdl import RGB

Transform = Callable[[RGB], RGB]

ALLOWED_SIZES = (17, 33, 65)
MAX_CUBE_BYTES = 64 * 1024 * 1024


class LUT3D:
    """A 3D LUT with red varying fastest (the .cube convention)."""

    def __init__(self, size: int, table: list[RGB], title: str = "resolve-assist") -> None:
        if size < 2 or size > 256:
            raise ValueError(f"LUT size {size} out of range 2..256")
        if len(table) != size**3:
            raise ValueError(f"LUT needs {size**3} entries, has {len(table)}")
        self.size = size
        self.table = table
        self.title = title

    @classmethod
    def identity(cls, size: int = 33) -> "LUT3D":
        return cls.from_transform(lambda rgb: rgb, size)

    @classmethod
    def from_transform(cls, fn: Transform, size: int = 33, title: str = "resolve-assist") -> "LUT3D":
        if size not in ALLOWED_SIZES:
            raise ValueError(f"size must be one of {ALLOWED_SIZES}")
        step = 1.0 / (size - 1)
        axis = [i * step for i in range(size)]
        table: list[RGB] = []
        for b in axis:
            for g in axis:
                for r in axis:
                    out = fn((r, g, b))
                    table.append(tuple(min(1.0, max(0.0, v)) for v in out))  # type: ignore[arg-type]
        return cls(size, table, title)

    def lookup(self, rgb: RGB) -> RGB:
        """Trilinear interpolation (used for previews and verification)."""
        n = self.size - 1
        idx = []
        frac = []
        for v in rgb:
            x = min(1.0, max(0.0, v)) * n
            i = min(int(x), n - 1)
            idx.append(i)
            frac.append(x - i)
        (ri, gi, bi), (rf, gf, bf) = idx, frac
        s = self.size
        t = self.table

        def at(r: int, g: int, b: int) -> RGB:
            return t[r + g * s + b * s * s]

        out = [0.0, 0.0, 0.0]
        for dr, wr in ((0, 1 - rf), (1, rf)):
            for dg, wg in ((0, 1 - gf), (1, gf)):
                for db, wb in ((0, 1 - bf), (1, bf)):
                    w = wr * wg * wb
                    if w:
                        c = at(ri + dr, gi + dg, bi + db)
                        out[0] += c[0] * w
                        out[1] += c[1] * w
                        out[2] += c[2] * w
        return (out[0], out[1], out[2])

    def to_cube(self) -> str:
        safe_title = self.title.replace('"', "'").replace("\n", " ")[:120]
        lines = [
            f'TITLE "{safe_title}"',
            "# Created by resolve-assist",
            f"LUT_3D_SIZE {self.size}",
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0",
        ]
        lines.extend(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in self.table)
        return "\n".join(lines) + "\n"

    def write(self, path: Path) -> None:
        path.write_text(self.to_cube(), encoding="ascii")

    @classmethod
    def read(cls, path: Path) -> "LUT3D":
        if path.stat().st_size > MAX_CUBE_BYTES:
            raise ValueError("cube file too large")
        return cls.parse(path.read_text(encoding="utf-8", errors="strict"))

    @classmethod
    def parse(cls, text: str) -> "LUT3D":
        size = None
        title = ""
        table: list[RGB] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key = line.split(None, 1)[0].upper()
            if key == "TITLE":
                title = line[5:].strip().strip('"')
            elif key == "LUT_3D_SIZE":
                size = int(line.split()[1])
            elif key == "LUT_1D_SIZE":
                raise ValueError("1D LUTs are not supported")
            elif key in ("DOMAIN_MIN", "DOMAIN_MAX"):
                vals = [float(v) for v in line.split()[1:]]
                expected = [0.0] * 3 if key == "DOMAIN_MIN" else [1.0] * 3
                if vals != expected:
                    raise ValueError(f"unsupported {key} {vals}")
            else:
                parts = line.split()
                if len(parts) != 3:
                    raise ValueError(f"bad LUT line: {line[:60]}")
                vals = tuple(float(p) for p in parts)
                if not all(math.isfinite(v) for v in vals):
                    raise ValueError("non-finite value in LUT")
                table.append(vals)  # type: ignore[arg-type]
        if size is None:
            raise ValueError("missing LUT_3D_SIZE")
        return cls(size, table, title)
