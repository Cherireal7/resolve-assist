"""Beat-synced edit plans: which shot plays when, cut exactly on the beat.

Offline only: the result is a cut list (and storyboard) that a person can follow
or that the bridge can assemble later (Phase 5).
"""

from __future__ import annotations

from .fingerprint import similarity
from .shots import Shot


def plan_cuts(shots_by_source: list[tuple[str, list[Shot]]], beats: list[float], downbeats: list[float],
              duration: float, beats_per_cut: int = 2, order: str = "match") -> dict:
    if beats_per_cut < 1 or beats_per_cut > 16:
        raise ValueError("beats_per_cut must be 1..16")
    pool = [(src, s) for src, shots in shots_by_source for s in shots if s.end - s.start >= 0.3]
    if not pool:
        raise ValueError("no usable shots (all shorter than 0.3 s)")
    if len(beats) < 2:
        raise ValueError("music has no detectable beat")
    start = downbeats[0] if downbeats else beats[0]
    grid = [b for b in beats if b >= start - 1e-6 and b <= duration + 1e-6]
    cuts = grid[::beats_per_cut]
    if not cuts or cuts[0] > 0.05:
        cuts = [0.0] + cuts           # open on frame 0, first cut lands on the downbeat
    if cuts[-1] < duration - 0.05:
        cuts.append(duration)

    plan = []
    used: list[int] = []
    prev = None
    for k in range(len(cuts) - 1):
        length = cuts[k + 1] - cuts[k]
        fits = [i for i in range(len(pool)) if i not in used] or list(range(len(pool)))
        if order == "match" and prev is not None:
            # Prefer the shot whose opening frame rhymes with the previous shot's last frame.
            i = max(fits, key=lambda j: similarity(prev.last, pool[j][1].first)["total"])
            reason = f"match cut (similarity {similarity(prev.last, pool[i][1].first)['total']:.2f})"
        else:
            i = fits[0]
            reason = "next shot in order"
        used.append(i)
        src, shot = pool[i]
        avail = shot.end - shot.start
        if avail >= length:
            src_in = min(max(shot.start, shot.best_time - length / 2), shot.end - length)
            note = None
        else:
            src_in, note = shot.start, f"shot is {avail:.2f}s, needs {length:.2f}s: hold or speed-ramp"
        plan.append({
            "timeline_in": round(cuts[k], 3), "duration": round(length, 3), "source": src, "shot": shot.index,
            "source_in": round(src_in, 3), "source_out": round(src_in + min(length, avail), 3),
            "why": reason, **({"note": note} if note else {}),
        })
        prev = shot
    return {"cuts_on_beats": [round(c, 3) for c in cuts], "beats_per_cut": beats_per_cut, "segments": plan}
