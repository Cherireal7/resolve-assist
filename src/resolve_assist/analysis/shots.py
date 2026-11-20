"""Shot detection and match-cut finding on sampled thumbnails."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..color.cdl import luma
from ..imaging.png import Image
from .fingerprint import Fingerprint, fingerprint, similarity

Frame = tuple[float, Image]  # (time in seconds, thumbnail)


def _hist(img: Image, bins: int = 16) -> list[float]:
    h = [0] * bins
    for p in img.pixels:
        h[min(bins - 1, int(luma(*p) * bins))] += 1
    n = len(img.pixels)
    return [v / n for v in h]


def _difference(ha: list[float], hb: list[float], fa: Fingerprint, fb: Fingerprint) -> float:
    hist_d = 0.5 * sum(abs(x - y) for x, y in zip(ha, hb))
    layout_d = sum(abs(x - y) for x, y in zip(fa.layout, fb.layout)) / len(fa.layout)
    return min(1.0, 0.6 * hist_d + 0.4 * min(1.0, layout_d * 4))


def frame_difference(a: Image, b: Image) -> float:
    """0 (same) .. 1 (completely different): luma histogram + coarse layout change."""
    return _difference(_hist(a), _hist(b), fingerprint(a), fingerprint(b))


@dataclass
class Shot:
    index: int
    start: float
    end: float          # time of the last sampled frame (exclusive end = next shot start)
    first: Fingerprint
    last: Fingerprint
    best_time: float    # sharpest frame
    sharpness: float

    def to_dict(self) -> dict:
        return {"index": self.index, "start": round(self.start, 3), "end": round(self.end, 3),
                "duration": round(self.end - self.start, 3), "best_frame_time": round(self.best_time, 3),
                "sharpness": round(self.sharpness, 5)}


def detect_shots(frames: list[Frame], min_threshold: float = 0.30, min_shot: float = 0.5) -> list[Shot]:
    """Cut where a frame differs much more than its neighbours usually do (adaptive threshold)."""
    if not frames:
        return []
    fps_all = [fingerprint(img) for _, img in frames]   # computed once per frame
    hists = [_hist(img) for _, img in frames]
    diffs = [0.0] + [_difference(hists[i - 1], hists[i], fps_all[i - 1], fps_all[i]) for i in range(1, len(frames))]
    cuts = [0]
    for i in range(1, len(frames)):
        # "Typical change" is measured inside the current shot only, so an earlier cut can't
        # inflate the threshold and hide the next one.
        window = diffs[max(cuts[-1] + 1, i - 8):i]
        mu = sum(window) / len(window) if window else 0.0
        sd = math.sqrt(sum((d - mu) ** 2 for d in window) / len(window)) if window else 0.0
        if diffs[i] > max(min_threshold, mu + 3 * sd) and frames[i][0] - frames[cuts[-1]][0] >= min_shot:
            cuts.append(i)
    shots = []
    bounds = cuts + [len(frames)]
    for k in range(len(cuts)):
        seg = frames[bounds[k]:bounds[k + 1]]
        fps_ = fps_all[bounds[k]:bounds[k + 1]]
        best = max(range(len(seg)), key=lambda j: fps_[j].sharpness)
        end = frames[bounds[k + 1]][0] if bounds[k + 1] < len(frames) else seg[-1][0]
        shots.append(Shot(k, seg[0][0], end, fps_[0], fps_[-1], seg[best][0], fps_[best].sharpness))
    return shots


def _reasons(sim: dict[str, float]) -> list[str]:
    out = []
    if sim["layout"] > 0.7:
        out.append("same composition (bright/dark masses in the same places)")
    if sim["shape"] > 0.75:
        out.append("matching line/shape directions")
    if sim["position"] > 0.8:
        out.append("subject/brightness at the same screen position")
    if sim["color"] > 0.7:
        out.append("color rhyme")
    return out


def match_cuts(shots: list[Shot], top: int = 5, min_score: float = 0.55) -> list[dict]:
    """Rank 'end of shot A → start of shot B' pairs that would make a match cut."""
    cands = []
    for a in shots:
        for b in shots:
            if a.index == b.index:
                continue
            sim = similarity(a.last, b.first)
            if sim["total"] >= min_score:
                cands.append({
                    "from_shot": a.index, "to_shot": b.index,
                    "cut_out_at": round(a.end, 3), "cut_in_at": round(b.start, 3),
                    "score": round(sim["total"], 3),
                    "aspects": {k: round(v, 3) for k, v in sim.items() if k != "total"},
                    "why": _reasons(sim) or ["overall similarity"],
                    "adjacent": b.index == a.index + 1,
                })
    cands.sort(key=lambda c: -c["score"])
    return cands[:top]


def windows(frames: list[Frame], shots: list[Shot], length: float) -> list[Shot]:
    """Split shots into non-overlapping beat-length moments, each with its own fingerprints,
    so an edit can use many different moments of one long take instead of repeating one."""
    if length <= 0:
        raise ValueError("length must be > 0")
    out: list[Shot] = []
    for shot in shots:
        inside = [(t, img) for t, img in frames if shot.start <= t < shot.end + 1e-6]
        if not inside:
            continue
        t = shot.start
        while t + length <= shot.end + 1e-6 or (t == shot.start and shot.end - shot.start >= 0.3):
            a, b = t, min(t + length, shot.end)
            seg = [(ft, img) for ft, img in inside if a - 1e-6 <= ft <= b + 1e-6] or [min(inside, key=lambda f: abs(f[0] - a))]
            fps_ = [fingerprint(img) for _, img in (seg[0], seg[-1])]
            mid = min(seg, key=lambda f: abs(f[0] - (a + b) / 2))
            out.append(Shot(len(out), a, b, fps_[0], fps_[-1], mid[0], max(f.sharpness for f in fps_)))
            out[-1].extra_parent = shot.index  # type: ignore[attr-defined]
            if b >= shot.end - 1e-6:
                break
            t += length
    return out
