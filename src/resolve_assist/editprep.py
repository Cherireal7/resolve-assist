"""Edit preparation for talking-head clips: word-level transcript, silence removal, planning page.

The flow (all local, no Resolve needed):
1. `prepare`  : transcribe word by word, find silences, keep speech with a small padding, optionally
                render the tightened clip, and split the script into short segments.
2. `plan_page`: an HTML page with the clip and script on the right and, per segment, a scene-type
                choice and a notes box on the left. "Copy plan" hands the decisions back to the AI.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from .analysis.beats import read_wav_mono
from .analysis.video import extract_audio
from .captions import Cue, transcribe
from .paths import find_ffmpeg

# Scene types of the MinimalStory template in Motion Studio (ids must match its schema).
SCENE_TYPES: dict[str, str] = {
    "aroll": "Speaker on screen with cinematic captions (use when a new idea is announced)",
    "broll": "Background clip with paper texture and soft dark edges, text on top (show what is described)",
    "painting": "A painting with texture, text around its subject, quick slide-in (stories, philosophy)",
    "line-text": "A line that draws through key words, camera follows (a chain of related ideas)",
    "line-illustration": "A line leading to illustrations or phases (progression, steps)",
    "quote": "Quotation marks and centred text on paper (the one line to remember, endings)",
    "center-illustration": "Abstract illustration in the centre with text around it (the main idea)",
    "side-illustration": "Illustration on one side, text on the other (two elements at once)",
    "object-callout": "One object or person with labels around it (a concrete example)",
    "graph": "A line drawn by a moving dot on a dark grid (numbers, growth, steady, decline)",
}


def find_silences(samples: list[float], rate: int, min_silence: float = 0.4, drop_db: float = 32.0) -> list[tuple[float, float]]:
    """Stretches quieter than (loudest speech level - drop_db) that last at least min_silence seconds."""
    hop = max(1, int(rate * 0.01))
    levels = []
    for i in range(0, len(samples) - hop + 1, hop):
        e = sum(x * x for x in samples[i:i + hop]) / hop
        levels.append(10 * math.log10(e + 1e-12))
    if not levels:
        return []
    loud = sorted(levels)[int(len(levels) * 0.95)]
    threshold = max(loud - drop_db, -60.0)
    out, start = [], None
    for k, lv in enumerate([*levels, 0.0]):          # sentinel closes a trailing silence
        quiet = lv < threshold and k < len(levels)
        if quiet and start is None:
            start = k
        elif not quiet and start is not None:
            a, b = start * hop / rate, k * hop / rate
            if b - a >= min_silence:
                out.append((round(a, 3), round(b, 3)))
            start = None
    return out


def keep_ranges(duration: float, silences: list[tuple[float, float]], padding: float = 0.03) -> list[tuple[float, float]]:
    """Everything except the silences, leaving `padding` seconds of each silence on both sides."""
    keeps, pos = [], 0.0
    for a, b in silences:
        a2, b2 = a + padding, b - padding
        if b2 - a2 <= 0.02:
            continue
        if a2 > pos:
            keeps.append((round(pos, 3), round(a2, 3)))
        pos = b2
    if duration - pos > 0.02:
        keeps.append((round(pos, 3), round(duration, 3)))
    return keeps


def remap(t: float, keeps: list[tuple[float, float]]) -> float:
    """Time in the original clip -> time in the tightened clip."""
    acc = 0.0
    for a, b in keeps:
        if t <= a:
            return round(acc, 3)
        if t < b:
            return round(acc + t - a, 3)
        acc += b - a
    return round(acc, 3)


def segments_from_words(words: list[Cue], max_words: int = 18, gap: float = 0.6) -> list[dict]:
    """Short script segments: split on sentence punctuation, long pauses, a comma once the segment
    is long enough, or after max_words."""
    segs: list[dict] = []
    cur: list[Cue] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = re.search(r"[.!?።]$", w.text.strip()) is not None
        pause = nxt is not None and nxt.start - w.end > gap
        comma = len(cur) >= 8 and w.text.strip().endswith((",", ";", ":", "፣"))
        if end or pause or comma or len(cur) >= max_words or nxt is None:
            segs.append({"id": len(segs) + 1, "start": round(cur[0].start, 3), "end": round(cur[-1].end, 3),
                         "text": " ".join(c.text.strip() for c in cur)})
            cur = []
    return segs


def render_tight(src: Path, keeps: list[tuple[float, float]], out: Path) -> None:
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg is needed to render the tightened clip: brew install ffmpeg")
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keeps)
    graph = (f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
             f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]")
    cmd = [ff, "-nostdin", "-hide_banner", "-v", "error", "-y", "-protocol_whitelist", "file", "-i", "file:" + str(src),
           "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, timeout=3600, check=False)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[-400:] or "ffmpeg failed")


def prepare(src: Path, out_dir: Path, min_silence: float = 0.4, padding: float = 0.03, model: str = "base",
            language: str = "auto", render: bool = True, log=lambda m: None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = extract_audio(src, 16000)
    try:
        samples, rate = read_wav_mono(wav)
    finally:
        shutil.rmtree(wav.parent, ignore_errors=True)
    duration = len(samples) / rate
    silences = find_silences(samples, rate, min_silence)
    keeps = keep_ranges(duration, silences, padding)
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", src.stem).strip() or "clip"
    video = src
    log("transcribing word by word…")
    if render and keeps and silences:
        video = out_dir / f"{stem}-tight.mp4"
        render_tight(src, keeps, video)
        # Word times are measured on the tightened clip itself: speech models place words loosely,
        # so mapping times from the original through the cuts can drop or misplace words.
        tight = transcribe(video, model=model, language=language, max_chars=1, log=log)
    else:
        words = transcribe(src, model=model, language=language, max_chars=1, log=log)
        tight = []
        for w in words:
            a = remap(w.start, keeps)
            tight.append(Cue(a, max(remap(w.end, keeps), a + 0.08), w.text))
    segs = segments_from_words(tight)
    data = {"source": str(src), "video": str(video), "duration": round(duration, 3),
            "tight_duration": round(sum(b - a for a, b in keeps), 3), "removed_seconds": round(duration - sum(b - a for a, b in keeps), 3),
            "padding": padding, "keep": keeps, "segments": segs,
            "words": [{"start": w.start, "end": w.end, "text": w.text.strip()} for w in tight]}
    (out_dir / f"{stem}.prep.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return {**{k: data[k] for k in ("video", "duration", "tight_duration", "removed_seconds", "segments")},
            "silences_cut": len(silences), "word_count": len(tight), "prep_file": str(out_dir / f"{stem}.prep.json")}


def plan_page(out: Path, video: Path, segments: list[dict], recommendations: dict | None = None, title: str = "Edit plan") -> Path:
    """Write the planning page. recommendations: {segment id: [scene type ids, best first]}."""
    recs = {str(k): [t for t in v if t in SCENE_TYPES] for k, v in (recommendations or {}).items()}
    try:
        rel = Path(os.path.relpath(video, out.parent)).as_posix()
    except ValueError:
        rel = video.as_posix()
    data = json.dumps({"video": rel, "segments": segments, "types": SCENE_TYPES, "recs": recs},
                      ensure_ascii=False).replace("</", "<\\/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.replace("__TITLE__", html.escape(title)).replace("__DATA__", data), encoding="utf-8")
    return out


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#131217;--panel:#1b1a21;--line:#2f2d39;--text:#eceaf2;--dim:#9793a6;--accent:#fb7a3c;--ok:#33cdb4}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:16px;padding:14px 22px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2}
h1{font-size:17px;margin:0;flex:1}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:8px 16px;background:var(--accent);color:#17120f;cursor:pointer}
button:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#count{color:var(--dim);font-variant-numeric:tabular-nums}
main{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px;padding:22px;align-items:start}
.seg{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.seg.now{border-color:var(--accent)}
.pick label{display:block;color:var(--dim);font-size:12.5px;margin-bottom:5px}
select,textarea{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit}
textarea{min-height:54px;margin-top:8px;resize:vertical}
.hint{color:var(--dim);font-size:12.5px;margin-top:6px;min-height:1.5em}
.say{cursor:pointer}
.say time{color:var(--dim);font-size:12.5px;font-variant-numeric:tabular-nums}
.say p{margin:4px 0 0;font-size:16.5px}
aside{position:sticky;top:74px}
video{width:100%;border-radius:12px;background:#000;max-height:calc(100vh - 110px)}
@media (max-width:900px){main{grid-template-columns:1fr}aside{position:static;order:-1}.seg{grid-template-columns:1fr}}
</style></head><body>
<header><h1>__TITLE__</h1><span id="count"></span><button id="copy">Copy plan</button></header>
<main><div id="list"></div><aside><video id="v" controls playsinline></video></aside></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent), v = document.getElementById('v'), list = document.getElementById('list');
v.src = encodeURI(D.video);
const fmt = t => Math.floor(t / 60) + ':' + (t % 60).toFixed(2).padStart(5, '0');
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
const rows = D.segments.map(s => {
  const row = el('div', 'seg'), pick = el('div', 'pick'), say = el('div', 'say');
  const lab = el('label', '', 'Scene for segment ' + s.id), sel = el('select'), hint = el('div', 'hint'), note = el('textarea');
  lab.htmlFor = sel.id = 'scene-' + s.id; note.placeholder = 'Notes: what to show, which words to emphasise…'; note.setAttribute('aria-label', 'Notes for segment ' + s.id);
  const rec = D.recs[String(s.id)] || [];
  for (const id of [...rec, ...Object.keys(D.types).filter(k => !rec.includes(k))]) {
    const o = el('option', '', id + (rec.includes(id) ? '  (recommended)' : '')); o.value = id; sel.append(o);
  }
  sel.value = rec[0] || 'aroll'; const show = () => { hint.textContent = D.types[sel.value]; update(); }; sel.onchange = show;
  note.oninput = () => update();
  pick.append(lab, sel, hint, note);
  say.append(el('time', '', fmt(s.start) + ' – ' + fmt(s.end)), el('p', '', s.text));
  say.onclick = () => { v.currentTime = s.start; v.play().catch(() => {}); };
  row.append(pick, say); list.append(row); hint.textContent = D.types[sel.value];
  return {s, row, sel, note};
});
function update() { const n = rows.filter(r => r.sel.value !== 'aroll').length; document.getElementById('count').textContent = rows.length + ' segments · ' + n + ' with visuals'; }
v.ontimeupdate = () => rows.forEach(r => r.row.classList.toggle('now', v.currentTime >= r.s.start && v.currentTime < r.s.end));
document.getElementById('copy').onclick = async e => {
  const text = 'EDIT PLAN\n' + rows.map(r => `${r.s.id}. [${fmt(r.s.start)}-${fmt(r.s.end)}] ${r.sel.value}\n   says: ${r.s.text}` + (r.note.value.trim() ? `\n   notes: ${r.note.value.trim()}` : '')).join('\n');
  try { await navigator.clipboard.writeText(text); } catch (_) { const t = el('textarea'); t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove(); }
  e.target.textContent = 'Copied'; setTimeout(() => e.target.textContent = 'Copy plan', 1500);
};
update();
</script></body></html>
"""
