# resolve-assist: project plan

> A local AI assistant for color correction and grading in **DaVinci Resolve Free**,
> built so that quality, security, fallbacks, performance and future updates are
> designed in from day one, not bolted on later.

Status: **v0.1.0 (Phase 0 + Phase 1)**, started 2026-11-16.
Target machine: macOS, DaVinci Resolve **Free 21.2.0**, Python 3.10+.

---

## 1. Goal

Let an AI assistant (Claude Code, Claude Desktop, or any MCP client) help with
color work on footage edited in Resolve Free:

1. **See** the footage: exposure, white balance, contrast, clipping, saturation.
2. **Correct** it: neutral balance and exposure, as exact numbers (ASC-CDL).
3. **Grade** it: create looks ("warm film", "teal & orange", "bleach bypass") and
   match shot B to shot A.
4. **Deliver** the result in a form Resolve Free accepts: a `.cube` LUT and/or CDL
   values, and later (Phase 2) apply them to clips directly.

### Non-goals

- Replacing hand grading: curves, qualifiers and power windows stay manual.
- Unlocking Studio-only features (Magic Mask, noise reduction, HDR, neural tools).
- Cloud processing. Everything runs locally and media never leaves the machine.

### Success criteria

| # | Criterion | How we verify |
|---|---|---|
| S1 | Analyze a still exported from Resolve and report a useful measurement | `resolve-assist analyze still.png`, numbers match a reference image in tests |
| S2 | Generate a LUT that Resolve Free loads and that visibly does what it says | Load in Resolve → Color page → node → LUT; manual test log in `docs/TESTING.md` |
| S3 | Auto-balance: a shot with a color cast becomes neutral (cast < 2%) | Unit test with a synthetic cast image |
| S4 | Shot match: shot B's mean/contrast lands within tolerance of shot A | Unit test with synthetic pair |
| S5 | Probe tells us exactly what Resolve Free 21.2's Lua API allows | `probe-report.json` captured from the real install |
| S6 | (Phase 2) AI applies a LUT/CDL to a clip on the open timeline | Live test on Free 21.2 |

---

## 2. Background: why it's built this way

- Since Resolve 21.1, **external scripting and the built-in MCP server are
  Studio-only**. Python scripts were also removed from the Free
  *Workspace → Scripts* menu. **Lua scripts started from inside Resolve still run.**
- Resolve Free **does** load `.cube` LUTs on any node, and the scripting API has
  `SetCDL` / `SetLUT` calls that a Lua script inside Resolve may reach.
- So we split the work:
  - **Off-Resolve engine (Python):** all analysis and LUT/CDL math. It needs no
    Resolve API, so it works on every version and can't damage a project.
  - **In-Resolve agent (Lua, Phase 2):** a thin, allowlisted executor that applies
    results to clips. Optional, and the system works fully without it.

Prior art reviewed (2026-11-16): `flamexnreal/davinci-resolve-ai-bridge-mcp`
(Lua file bridge; grading limited to CDL), `samuelgursky/davinci-resolve-mcp`
(Studio only). We write our own code; nothing is copied.

---

## 3. Architecture

```
 ┌──────────────┐  MCP (stdio)  ┌──────────────────────────────┐
 │ Claude / MCP │ ────────────▶ │ resolve-assist server (Py)   │
 │   client     │ ◀──────────── │  tools: analyze, balance,    │
 └──────────────┘               │  match, make_lut, looks ...  │
                                └──────┬──────────────┬────────┘
                                       │              │
                         decode media  │              │ write .cube / CDL
                                       ▼              ▼
                           ┌──────────────────┐  ┌────────────────────────┐
                           │ imaging/decode   │  │ output dir (allowlist) │
                           │ ffmpeg ─▶ PNG    │  │ ~/Documents/resolve-   │
                           │ (fallback chain) │  │ assist/LUTs + Resolve  │
                           └──────────────────┘  │ LUT folder (optional)  │
                                                 └───────────┬────────────┘
                                                             │ Phase 2
                                       file queue (0700 dir) ▼
                                                 ┌────────────────────────┐
                                                 │ Lua agent in Resolve   │
                                                 │ allowlisted ops only:  │
                                                 │ SetLUT, SetCDL, read   │
                                                 └────────────────────────┘
```

### Modules

| Path | Responsibility | Depends on |
|---|---|---|
| `src/resolve_assist/color/cdl.py` | ASC-CDL math (slope/offset/power/sat), Rec.709 luma | stdlib |
| `src/resolve_assist/color/lut.py` | `.cube` write/read/validate, sample LUT from a function | stdlib |
| `src/resolve_assist/color/looks.py` | Named looks as parameter sets plus a tone curve | `cdl` |
| `src/resolve_assist/color/correct.py` | Auto balance and shot match → CDL | `analyze` |
| `src/resolve_assist/imaging/png.py` | Pure-Python PNG decoder (8/16-bit, all filters) | stdlib (`zlib`) |
| `src/resolve_assist/imaging/decode.py` | Decoder chain: ffmpeg → macOS sips → built-in PNG | `png`, optional ffmpeg/sips |
| `src/resolve_assist/analyze.py` | Stats: per-channel mean, percentiles, clipping, cast, histogram | `decode` |
| `src/resolve_assist/paths.py` | Config, safe input/output path checks | stdlib |
| `src/resolve_assist/server.py` | MCP tools (thin wrappers) | `mcp` (optional extra) |
| `src/resolve_assist/cli.py` | Same features as a CLI; probe install/report | stdlib |
| `src/resolve_assist/lua/probe.lua` | Read-only capability probe inside Resolve | Resolve Lua |

Rules: core packages are **stdlib-only**. `mcp` is the only runtime dependency
and only for the server. The CLI works without it.

---

## 4. Implementation phases

### Phase 0: Probe (v0.1)
- [x] `probe.lua`: read-only; records the Resolve version, product, Lua libraries (`io`, `os`,
      `ffi`), `bmd.*` file helpers, project/timeline access, availability of
      color methods (`SetCDL`, `SetLUT`, `GetNodeGraph`, `ApplyGradeFromDRX` ...).
- [x] Writes `~/.resolve-assist/probe-report.json` with a fallback chain
      (`io` → `bmd.writefile` → console print).
- [x] `resolve-assist install-probe` / `resolve-assist probe-report`.
- [x] Run on the real Free 21.2 install → recorded in `docs/COMPATIBILITY.md` (2026-11-17).

### Phase 1: Offline grading engine + MCP (v0.1)
- [x] Analyze stills/frames; built-in PNG decoder; ffmpeg when present.
- [x] CDL + saturation math, Resolve-compatible order.
- [x] `.cube` writer/reader (17/33/65 points), validation.
- [x] Auto balance (gray-world plus a white patch), exposure normalization.
- [x] Shot match (per-channel mean/std transfer → CDL).
- [x] Look library (6 starter looks) with strength control.
- [x] MCP server + CLI.
- [x] Live: Resolve Free 21.2 (App Store) refuses LUTs from outside its LUT folders → CDL fallback (see Phase 2).

### Phase 2: In-Resolve agent (v0.2)
- [x] Transport proven by the probe: shared folder `~/Documents/resolve-assist/bridge` + `fu:OpenFile`
      (works in the sandboxed App Store build; no `io` there).
- [x] Allowlisted ops: `status`, `list_clips`, `clip_info`, `goto_clip`, `grab_frame`,
      `apply_cdl`, `apply_lut`, `undo`, `stop`. Request data is never executed.
- [x] Safety: dry run by default (`confirm=true` needed), changes go into a separate
      `resolve-assist` grade version (undo = load the previous version), LUTs only from the
      LUT folder, session id + 60 s expiry, journal of every call.
- [x] Heartbeat; Scripts-menu entry installed by the bridge on first run.
- [x] End-to-end tests: real `bridge.lua` in LuaJIT/Lua 5.1 (lupa) ↔ real client through real files.
- [x] Live test on Free 21.2 (App Store), 2026-11-17: start, status, list, grab (frames include the
      grade), apply CDL in a new `resolve-assist` version, stabilize, look via CDL approximation,
      music on a timeline copy: all ✅. LUT load ❌ (Resolve refuses outside its LUT folders).
- [ ] **Open bug: Fusion title does not render.** Text+ → Merge → MediaOut nodes exist inside the
      clip comp (verified by tool list) but neither the viewer nor exported frames show text.
      Next checks: read back MediaOut's connected input; build nodes via `comp:Execute()` in comp
      context (what the reviewed Free bridge does); check comp `Lock()`; test a solid Background
      node instead of Text+ to separate "wiring" from "text".
- [ ] Find the color page LUT folder of the App Store build (Project Settings → Color Management →
      Open LUT Folder) so real LUTs work instead of the CDL approximation.

---

## 4b. Roadmap: from color assistant to AI editing partner

Principle (unchanged): every feature works **offline first** (analysis, plans, previews, files), and
the live bridge only applies the result: on a timeline copy or a separate grade version, with undo.
Feasibility marks: ✅ verified on Free 21.2 · 🔶 API exists, untested · 🧪 offline only · ⛔ Studio only.

### Phase 3: Fusion effects that render (v0.3)
Prerequisite for titles and most effects: fix the open Fusion bug above.
| Feature | How | Status |
|---|---|---|
| Titles / lower thirds (fade in/out, safe-area aware for 9:16) | Text+ inside the clip comp | 🔶 (bug) |
| Punch-in / slow zoom (Ken Burns), shake, whip-pan blur | Transform + keyframes in clip comp | 🔶 |
| Blur, glow, vignette, film grain, light leaks | Fusion tools in a bridge-owned chain before MediaOut | 🔶 |
| Speed ramps / freeze frames | TimeSpeed node in comp (reviewed bridge does this on Free) | 🔶 |
| Effect presets as JSON (`effects/*.json`) the AI can combine | ours | 🧪 |

### Phase 4: Analysis engine (v0.4): "understand the footage"
| Feature | How | Status |
|---|---|---|
| Shot/scene detection, best-frame picker per shot | frame differences on ffmpeg-decoded thumbnails (or frames grabbed via bridge) | 🧪 |
| Visual fingerprints per shot start/end: luma layout grid, edge-orientation histogram, dominant colors, brightness centroid, motion direction | stdlib math on thumbnails | 🧪 |
| **Match-cut finder**: rank shot pairs whose end/start frames share shape, position, color or motion; suggest exact cut frames | fingerprint similarity | 🧪 |
| Music analysis: tempo, beat grid, downbeats, energy curve | stdlib onset detection on WAV (ffmpeg decodes mp3) | 🧪 |
| Shake / blur / exposure problems per shot (choose what to stabilize or drop) | frame stats | 🧪 |
| Speech segments (silence detection) for talking-head cuts | audio RMS | 🧪 |

### Phase 5: Edit assembly (v0.5): "make the cut"
| Feature | How | Status |
|---|---|---|
| Rough cut from selected shots (in/out ranges) on a new timeline | `MediaPool:CreateEmptyTimeline` + `AppendToTimeline` with ranges | 🔶 |
| **Beat-synced cutting**: cut points snapped to beats/downbeats | analysis + append ranges | 🧪→🔶 |
| **Match cuts / jump cuts** placed from the finder; J/L-cut audio offsets | append ranges per track | 🔶 |
| Markers for beats, best moments, problems | `Timeline:AddMarker` | 🔶 |
| Transitions (cross-dissolve, dip, zoom/whip) | Fusion transition comps or overlap + Merge blend | 🔶 |
| Vertical (9:16) / 4:5 / 1:1 timeline copies, clips scaled to fit | `Timeline:SetSetting` (Smart Reframe is ⛔) | 🔶 built, live test pending |
| Auto captions (local whisper.cpp → SRT → subtitle track) | CapCut-style; Resolve's AI subtitles are ⛔ Studio | 🔶 built, live test pending |
| Edit plan preview without Resolve: storyboard PNG + timing sheet | ours | 🧪 |

### Phase 6: Delivery (v0.6)
| Feature | How | Status |
|---|---|---|
| Render queue with presets (Instagram/TikTok/YouTube), Free limits (UHD/60) checked first | `SetRenderSettings`, `AddRenderJob`, `StartRendering` | 🔶 |
| Loudness check of the export (target −14 LUFS for social) | offline audio analysis | 🧪 |
| Thumbnail / cover frame suggestions | best-frame picker | 🧪 |

### Phase 7: Polish & platform (v1.0)
- One-command setup (`resolve-assist setup`: venv, MCP registration, bridge install).
- Claude Code skill/prompt with the full workflow; MCP prompts for "grade this", "cut to the beat".
- Docs with screenshots; compatibility matrix; release automation (tags → GitHub releases).
- Optional: look and effect library browser (local HTML page) with previews.

### Order of work
1. Phase 4 analysis engine (fully testable offline, no Resolve needed) → match-cut finder + beat grid.
2. Fix the Fusion render bug (needs one live session) → Phase 3 effects.
3. Phase 5 assembly on timeline copies → Phase 6 delivery → Phase 7.

---

## 5. Quality standards

- **Typed Python** (`from __future__ import annotations`, type hints on public functions).
- **Tests first for math:** every color function has a unit test against known
  values (identity LUT, CDL round-trip, Rec.709 luma weights, PNG filters).
- **No hidden behavior:** a tool only writes where its docstring says it writes.
- **Small modules** (< ~400 lines); server/CLI are thin wrappers over the library.
- **CI** (GitHub Actions): tests on Linux/macOS, Python 3.10 and the newest supported version; actions pinned by SHA,
  `permissions: contents: read`.
- **Commit style:** Conventional Commits (`feat:`, `fix:`, `docs:` ...).
- **Definition of done:** tests pass, docs and CHANGELOG updated, compatibility
  table updated if Resolve behavior was touched.

---

## 6. Security model

Threats: the AI client is driven by text that may contain prompt injection (file
names, metadata, web content). So **tool inputs are treated as untrusted**.

| Risk | Mitigation |
|---|---|
| Reading arbitrary files (e.g. `~/.ssh`) via `analyze` | Only media extensions allowed; must be a regular file; size cap; never return file contents, only statistics |
| Writing anywhere via `make_lut` | Output name sanitized (`[A-Za-z0-9 _-]`), always written inside the output dir allowlist; no path traversal; never overwrites unless `overwrite=true` |
| ffmpeg argument/protocol injection | `subprocess.run([...])` (no shell); input passed as `file:` + absolute path; `-nostdin`, `-protocol_whitelist file`; timeout |
| Malicious PNG (decompression bomb) | Dimension and decompressed-size caps before inflating |
| Phase 2 queue tampering | Queue dir `0700`, files `0600`, per-install random token, op allowlist, **no `loadstring` of request data**, request expiry |
| Supply chain | One runtime dep (`mcp`) with a version range; CI actions pinned by SHA; no install-time downloads from `main` |
| Damaging a project | Phase 1 never touches Resolve. Phase 2: dry-run + undo record + user confirmation for destructive ops |

Report issues privately; see `SECURITY.md`.

---

## 7. Fallbacks (graceful degradation)

| If this fails... | ...we fall back to |
|---|---|
| ffmpeg not installed | macOS `sips` (PNG/TIFF/JPEG stills, fast) → built-in PNG decoder |
| `mcp` SDK not installable | CLI does everything; Claude Code can call the CLI |
| Resolve LUT folder missing | Write to `~/Documents/resolve-assist/LUTs` and print how to load it |
| Lua `io` blocked in Resolve | `bmd.writefile` → console print the user can paste |
| Phase 2 agent offline / API missing | Phase 1 output (LUT/CDL) applied by hand: always works |
| Analysis looks wrong (log footage, extreme scene) | Report confidence + warnings; never auto-apply below a confidence threshold |

---

## 8. Performance budget

| Operation | Budget | Approach |
|---|---|---|
| Analyze a 4K still | < 1.5 s | ffmpeg/sips scale to ≤ 512 px first; built-in PNG decoder is the slow last resort (~3 s) |
| 33³ LUT generation | < 0.5 s | Pure Python over 35,937 points; pre-computed curve tables |
| Server startup | < 1 s | Lazy imports; no work at import time |
| Memory | < 200 MB | Never hold full-res frames; stream decode rows |

Measured numbers go into `docs/TESTING.md` when they change.

---

## 9. Updates & compatibility

- **SemVer**: `0.x` while the API settles; breaking changes are noted in `CHANGELOG.md`.
- **Resolve updates:** after each Resolve update, re-run the probe and diff it
  against the stored report (`resolve-assist probe-report --diff`, planned for Phase 2).
  Record the result in `docs/COMPATIBILITY.md`.
- **Dependencies:** check `mcp` releases monthly; bump the range only after tests pass.
- **Python:** support the oldest version still in security support plus the newest.

## 10. Improvement process

1. Every issue/idea becomes a GitHub issue labeled `bug`, `feature`, `perf`, `security` or `compat`.
2. Real-world grading sessions → note what the AI got wrong in `docs/FIELD-NOTES.md`
   → turn it into a test case (e.g. a sample PNG + expected correction).
3. Review the roadmap at the end of each phase; move unfinished items forward.

---

## 11. Testing strategy

- **Unit:** color math, LUT I/O, PNG decoder, path security, analysis on synthetic images.
- **Integration:** MCP tool calls via the SDK's in-process client (when `mcp` is installed).
- **Manual (Resolve):** checklist in `docs/TESTING.md`: probe run, LUT load,
  before/after visual check. Each run is logged with the Resolve version and date.
