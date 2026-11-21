"""Library browser: one self-contained HTML page (library/index.html) to see and hear every asset.

Opens straight from disk (no server): the manifest is embedded, media is referenced by relative path.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from ..color.looks import LOOKS, look_transform
from ..imaging.png import encode_png
from ..paths import find_ffmpeg

VIDEO_EXTS = (".mp4", ".mov")


def video_poster(root: Path, item: dict) -> None:
    """One small frame per clip, so the page shows every video (browsers can't decode ProRes .mov)."""
    import subprocess
    out = root / ".previews" / "video" / f"{item['id']}.png"
    src = root / item["file"]
    ff = find_ffmpeg()
    if not ff or (out.exists() and out.stat().st_mtime >= src.stat().st_mtime):
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    for at in ("0.9", "0.3", "0"):                  # later frames show more of an animation
        subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-ss", at, "-i", f"file:{src}", "-frames:v", "1",
                        "-vf", "scale=360:-2", str(out)], capture_output=True, timeout=60, check=False)
        if out.exists() and out.stat().st_size > 0:
            return

FONT_EXTS = (".ttf", ".otf")


def look_swatch(path: Path, name: str) -> None:
    """Small test card run through a look: hue ramp, skin tones and a gray ramp."""
    w, h = 240, 135
    fn = look_transform(LOOKS[name], 1.0)
    skins = [(0.96, 0.80, 0.69), (0.87, 0.66, 0.52), (0.71, 0.49, 0.36), (0.50, 0.33, 0.24), (0.33, 0.21, 0.15)]
    px = []
    for y in range(h):
        for x in range(w):
            u = x / w
            if y < 55:                                       # hue ramp, darker towards the bottom
                k = 6 * u
                rgb = [max(0.0, min(1.0, abs(((k + s) % 6) - 3) - 1)) for s in (0, 4, 2)]
                v = 1.0 - 0.6 * y / 55
                c = (rgb[0] * v, rgb[1] * v, rgb[2] * v)
            elif y < 100:
                c = skins[min(4, int(u * 5))]
            else:
                c = (u, u, u)
            px.append(fn(c))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_png(w, h, px))


def write_browser(root: Path, items: list[dict]) -> Path:
    for name in LOOKS:
        sw = root / ".previews" / "luts" / f"{name}.png"
        if not sw.exists():
            try:
                look_swatch(sw, name)
            except Exception:
                pass
    for it in items:
        if it["file"].lower().endswith(VIDEO_EXTS):
            try:
                video_poster(root, it)
            except Exception:
                pass
    data = json.dumps({"root": str(root), "items": items}, ensure_ascii=False).replace("</", "<\\/")
    faces = []
    for it in items:
        if it["category"] == "fonts" and it["file"].lower().endswith(FONT_EXTS):
            faces.append("@font-face{font-family:'lib-%s';src:url('%s');font-display:swap}"
                         % (html.escape(it["id"], quote=True), html.escape(it["file"], quote=True)))
    page = PAGE.replace("/*FACES*/", "\n".join(faces)).replace("__DATA__", data)
    out = root / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Asset library</title>
<style>
/*FACES*/
:root{--bg:#f6f5f2;--panel:#fff;--line:#e2dfd8;--text:#1c1b19;--dim:#6d6a63;--accent:#c2410c;--chip:#efece6;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--panel:#1e1e1c;--line:#32312e;--text:#eeece7;--dim:#9c988f;--accent:#fb923c;--chip:#2a2927}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:grid;grid-template-columns:210px 1fr;min-height:100vh}
nav{border-right:1px solid var(--line);padding:20px 12px;position:sticky;top:0;height:100vh;overflow:auto}
nav h1{font-size:15px;margin:0 8px 14px;letter-spacing:.01em}
nav button{display:flex;justify-content:space-between;width:100%;border:0;background:none;color:var(--text);font:inherit;padding:7px 8px;border-radius:6px;cursor:pointer;text-align:left}
nav button:hover{background:var(--chip)} nav button[aria-current=true]{background:var(--chip);font-weight:600}
nav button span{color:var(--dim);font-variant-numeric:tabular-nums;font-weight:400}
main{padding:20px 24px 60px;min-width:0}
.bar{display:flex;gap:12px;align-items:center;margin-bottom:18px;flex-wrap:wrap}
input[type=search]{flex:1;min-width:220px;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);font:inherit}
input[type=search]:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
#count{color:var(--dim);font-variant-numeric:tabular-nums}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
.grid.audio{grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.thumb{background:#111 conic-gradient(#2a2a2a 25%,#1c1c1c 0 50%,#2a2a2a 0 75%,#1c1c1c 0) 0 0/20px 20px;display:flex;align-items:center;justify-content:center;height:190px}
.thumb img,.thumb video{max-width:100%;max-height:100%;display:block}
.spec{padding:14px 12px 4px;font-size:30px;line-height:1.15;overflow-wrap:anywhere}
.body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.name{font-weight:600;overflow-wrap:anywhere}
.use{color:var(--dim)} .meta{color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.tags{display:flex;flex-wrap:wrap;gap:4px} .tags span{background:var(--chip);border-radius:20px;padding:1px 8px;font-size:12px;color:var(--dim)}
audio{width:100%;height:34px}
.row{display:flex;gap:8px;margin-top:auto;padding-top:4px}
.row button{border:1px solid var(--line);background:none;color:var(--text);font:inherit;font-size:12px;padding:4px 10px;border-radius:6px;cursor:pointer}
.row button:hover{border-color:var(--accent);color:var(--accent)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:26px 0 10px}
.empty{color:var(--dim);padding:40px 0}
@media (max-width:720px){body{grid-template-columns:1fr}nav{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}}
</style></head><body>
<nav><h1>Asset library</h1><div id="cats"></div></nav>
<main>
<div class="bar"><input id="q" type="search" placeholder="Search: whoosh, warm, vertical, ui, title…" autofocus><span id="count"></span></div>
<div id="out"></div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const ORDER = ['sfx','music','graphics','motion','overlays','transitions','backgrounds','textures','fonts','luts','powergrades','footage','ai-generated'];
const AUDIO = /\.(wav|mp3|m4a|aac)$/i, IMG = /\.(png|jpe?g|webp)$/i, VID = /\.(mp4|mov|webm)$/i, FONT = /\.(ttf|otf)$/i;
let cat = 'all', q = '';
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
const cats = [...new Set(DATA.items.map(i => i.category))].sort((a, b) => (ORDER.indexOf(a) + 99) % 99 - (ORDER.indexOf(b) + 99) % 99);
function nav() {
  const box = document.getElementById('cats'); box.textContent = '';
  for (const c of ['all', ...cats]) {
    const b = el('button'); b.append(el('b', '', c === 'all' ? 'Everything' : c), el('span', '', String(c === 'all' ? DATA.items.length : DATA.items.filter(i => i.category === c).length)));
    b.firstChild.style.fontWeight = 'inherit'; b.setAttribute('aria-current', c === cat);
    b.onclick = () => { cat = c; nav(); draw(); }; box.append(b);
  }
}
function card(it) {
  const c = el('div', 'card'), f = it.file, body = el('div', 'body');
  if (IMG.test(f)) { const t = el('div', 'thumb'), im = el('img'); im.loading = 'lazy'; im.src = encodeURI(f); im.alt = it.id; t.append(im); c.append(t); }
  else if (VID.test(f)) { const t = el('div', 'thumb'), im = el('img'); im.loading = 'lazy'; im.alt = it.id; im.src = '.previews/video/' + encodeURIComponent(it.id) + '.png'; t.append(im);
    if (/\.mp4$/i.test(f)) { let v; t.onmouseenter = () => { if (!v) { v = el('video'); v.muted = true; v.loop = true; v.playsInline = true; v.src = encodeURI(f); } t.replaceChildren(v); v.play().catch(() => {}); }; t.onmouseleave = () => { if (v) v.pause(); t.replaceChildren(im); }; }
    c.append(t); }
  else if (FONT.test(f)) { const s = el('div', 'spec', 'Aa Bb 123 ሰላም'); s.style.fontFamily = "'lib-" + it.id + "'"; c.append(s); }
  else if (it.category === 'luts') { const t = el('div', 'thumb'), im = el('img'); im.loading = 'lazy'; im.src = '.previews/luts/' + it.id.replace(/-50$/, '') + '.png'; im.alt = ''; im.style.width = '100%'; im.onerror = () => t.remove(); t.append(im); c.append(t); }
  body.append(el('div', 'name', it.id));
  if (it.usage) body.append(el('div', 'use', it.usage));
  const meta = [it.seconds ? it.seconds + ' s' : '', it.bpm ? it.bpm + ' BPM' : '', f.split('.').pop().toUpperCase()].filter(Boolean).join(' · ');
  body.append(el('div', 'meta', meta));
  if (AUDIO.test(f)) { const a = el('audio'); a.controls = true; a.preload = 'none'; a.src = encodeURI(f); body.append(a); }
  const tags = el('div', 'tags'); for (const t of (it.tags || []).slice(0, 6)) tags.append(el('span', '', t)); body.append(tags);
  const row = el('div', 'row'), cp = el('button', '', 'Copy path');
  cp.onclick = async () => { const p = DATA.root + '/' + f; try { await navigator.clipboard.writeText(p); } catch (e) { const ta = el('textarea'); ta.value = p; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); } cp.textContent = 'Copied'; setTimeout(() => cp.textContent = 'Copy path', 1200); };
  const open = el('button', '', 'Open file'); open.onclick = () => window.open(encodeURI(f));
  row.append(cp, open); body.append(row); c.append(body); return c;
}
function draw() {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean), out = document.getElementById('out'); out.textContent = '';
  const hits = DATA.items.filter(i => (cat === 'all' || i.category === cat) && words.every(w => (i.id + ' ' + i.category + ' ' + (i.usage || '') + ' ' + (i.tags || []).join(' ')).toLowerCase().includes(w)));
  document.getElementById('count').textContent = hits.length + ' of ' + DATA.items.length;
  if (!hits.length) { out.append(el('div', 'empty', 'Nothing matches. Try fewer words.')); return; }
  for (const c of cats) {
    const group = hits.filter(i => i.category === c); if (!group.length) continue;
    if (cat === 'all') out.append(el('h2', '', c + ' (' + group.length + ')'));
    const g = el('div', 'grid' + (AUDIO.test(group[0].file) ? ' audio' : '')); group.forEach(i => g.append(card(i))); out.append(g);
  }
}
document.getElementById('q').oninput = e => { q = e.target.value; draw(); };
document.addEventListener('play', e => { for (const a of document.querySelectorAll('audio')) if (a !== e.target) a.pause(); }, true);
nav(); draw();
</script></body></html>
"""
