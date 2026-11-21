from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

from resolve_assist.imaging.png import encode_png


def scene(width: int = 96, height: int = 64, cast=(1.0, 1.0, 1.0), gain: float = 1.0, seed: int = 7):
    """Synthetic frame: gray card patches + colored objects + noise, with an optional cast."""
    rnd = random.Random(seed)
    pixels = []
    for y in range(height):
        for x in range(width):
            if x < width // 2:
                v = 0.1 + 0.8 * (x / (width // 2))          # neutral ramp
                base = (v, v, v)
            elif y < height // 2:
                base = (0.7, 0.35, 0.25)                      # warm object
            else:
                base = (0.2, 0.45, 0.6)                       # cool object
            n = rnd.uniform(-0.01, 0.01)
            pixels.append(tuple(min(1.0, max(0.0, (c + n) * k * gain)) for c, k in zip(base, cast)))
    return width, height, pixels


def write_png(dirpath: Path, name: str, width: int, height: int, pixels, depth: int = 8) -> Path:
    p = dirpath / name
    p.write_bytes(encode_png(width, height, pixels, depth))
    return p


class TempEnv:
    """Points output/state dirs at a temp folder and hides any system ffmpeg."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("RESOLVE_ASSIST_OUTPUT", "RESOLVE_ASSIST_HOME",
                                                       "RESOLVE_ASSIST_LUT_DIR", "RESOLVE_ASSIST_FFMPEG", "PATH",
                                                       "RESOLVE_ASSIST_OBS_HOST", "RESOLVE_ASSIST_OBS_PORT",
                                                       "RESOLVE_ASSIST_OBS_PASSWORD_FILE")}
        os.environ["RESOLVE_ASSIST_OUTPUT"] = str(root / "out")
        os.environ["RESOLVE_ASSIST_HOME"] = str(root / "state")
        os.environ["RESOLVE_ASSIST_LUT_DIR"] = str(root / "resolve-luts")
        os.environ.pop("RESOLVE_ASSIST_FFMPEG", None)
        # never touch the real OBS or its password: tests point these at a fake server / temp file
        os.environ["RESOLVE_ASSIST_OBS_HOST"] = "127.0.0.1"
        os.environ["RESOLVE_ASSIST_OBS_PASSWORD_FILE"] = str(root / "obs-password")
        os.environ.pop("RESOLVE_ASSIST_OBS_PORT", None)
        self.root = root
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()
