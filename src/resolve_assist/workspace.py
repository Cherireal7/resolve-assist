"""Workspace setup and health checks: everything a new editing session needs."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from . import __version__
from .paths import find_ffmpeg, output_dir

PROJECT_DIRS = ("inbox", "footage", "stills", "maps", "refs", "voice", "music", "docs", "captions", "kit", "exports")
EDITORS = ("resolve", "capcut", "none")

WORKSPACE_GUIDE = """# Video studio workspace

Type `studio` in a terminal (or click the Studio icon) and this session starts here with this guide.
`studio help` lists the other one-word commands (new, open, library, kit, motion, fonts, doctor, editor).

## Start word
Say `cutroom` (alone, or followed by an idea, a project or a file) to start a video: it loads the `cutroom` skill,
which holds the style rules (`style.md`), the route for each kind of video and the phone-footage workflow. The same
word, skills and tools work in Claude Code (`studio`) and in Codex (`studio codex`); this guide is also written as
`AGENTS.md` for Codex.

## Which editor?
The editor is a choice, not a requirement: `studio editor resolve|capcut|none` sets the default,
stored in `~/.config/studio/config` (`editor=...`). Read that file at the start of a session.

| | DaVinci Resolve | CapCut (or any other editor) |
|---|---|---|
| Connection | live bridge (Workspace → Scripts → Utility → **resolve-assist Bridge**) | none: files are handed over |
| Assets | `import_assets` puts them in the Media Pool | `project_kit` copies them into `projects/<name>/kit/`, the user imports that folder |
| Captions | `auto_captions` onto a timeline copy | `auto_captions` on the video file → `.srt` → CapCut: Captions → Import file |
| Music / SFX | `make_music`, `add_music`, SFX on cuts | `make_music` + kit; beat times from `analyze_music` as a cut list |
| Grade | `apply_grade` (dry run first) | `make_lut` → `.cube` → CapCut: Adjustment → LUT |
| Graphics | Motion Studio renders → `import_assets` | Motion Studio renders → kit |

## Start cheap: read before you look
Every project keeps its own memory so work is never repeated:
- `projects/<name>/brief.md`: goal, style, decisions. Read it first; add one line under "Decisions and
  progress" whenever something is decided or finished.
- `projects/<name>/project.json`: every file with kind, duration and size (from `project_intake`).
  Use it instead of listing folders or probing files again.
- `prep/*.prep.json` (transcript, cuts), `prep/plan.html` (the chosen scenes), Motion Studio configs:
  reuse them; re-run a step only when its input changed.
- The user drops new material into `projects/<name>/inbox/` (footage, photos, map images, voice,
  references, scripts). Run `project_intake` to sort and index it.
- Map images (`maps/`) are for the `MapJourney` template: curved routes on a 3D-tilted map with a
  following camera. Ask for (or estimate, then show) the stop positions as x/y fractions of the image.
- Higgsfield is for what cannot be filmed or drawn in code (a product shot, a b-roll clip, an
  illustration with a specific look, image → video). Price first, wait for an OK, save the result into
  the project and the library so it is generated once.

## Editing a timeline (`projects/<name>/edit.json`)
The Tibeb editor, the renderer and you all work on this one file; the open editor reloads it when it
changes, and the user can undo. Shape: `{version: 1, duration, background, credit?, tracks: [...]}`,
tracks listed top layer first, each `{id, name, kind: text|video|audio, muted?, duck?, clips: [...]}`.
Times are seconds. Every clip has `id` (unique in the file), `start`, `length`, `kind`:
- `video` / `image`: `src`, `in` (seconds skipped at the source start), `volume`, `fit` (cover|contain),
  `scale`, `x`, `y` (% shift), `opacity`, `zoom` (slow push, -0.5..0.5); optional colour: `look`
  (golden-hour, warm-film, teal-orange, cool-night, bleach-bypass, clean-commercial, bw-contrast,
  vintage-fade, moody-teal, pastel-dream), `lookStrength` 0..1, `exposure`, `contrast`, `saturation`,
  `temperature`, `tint`.
- `text`: `text`, `style`, `typeface?`, `motion`, `size` (% of the short side), `color`, `accent`,
  `x`, `y` (centre, % from left/top), `align`.
- `audio`: `src`, `in`, `volume`, `fadeIn`, `fadeOut`.
`src` is `projects/<slug>/<file inside the project>` (slug = project name lower-cased with dashes).
Change only what was asked, keep all other fields, keep the JSON valid, and keep the end credit.

## Every session
1. Read `~/.config/studio/config` for the editor. Resolve: check `bridge_status`; if it is not running ask
   for the Scripts-menu click. CapCut/none: do not ask for Resolve or the bridge at all.
2. Ask what video is being made, or continue the project the user names (`projects/<name>/notes.md`).
3. Examples: "Check my setup" · "New project Nail Promo" · "Caption this clip" · "Make a kit with a whoosh,
   a warm light leak and uplifting music" · "Grade all clips naturally" (Resolve) · "Find match cuts and
   cut them to the beat" (Resolve builds the timeline; CapCut gets the cut list).

## The full pipeline
Higgsfield (AI images/clips, costs credits) → Motion Studio (`~/Documents/Github/motion-studio`,
animated graphics, text overlays, `npm run make -- <config> --to-resolve`) → this workspace + your editor
(edit, grade, captions, deliver). Full guide: `~/Documents/Github/motion-studio/docs/PIPELINE.md`.

Use both graphics engines in the same video, each for what it does best:
- Motion Studio builds the body: the story templates, camera moves and anything the user already liked.
- HyperFrames (`~/Documents/Github/hyperframes-studio`, HTML rendered to video, free and local) adds what the
  templates lack: one-off scenes, kinetic type, counters, charts, UI demos and registry blocks (search with
  `npx hyperframes catalog <word>` before hand-building an effect).
- Joining them: a full HyperFrames scene renders to MP4 and is cut in as a clip; an element that sits on top
  of other footage renders with `--format mov` (ProRes 4444 with transparency) and goes on a track above.
  Either file is dropped in the project's `inbox/` here, then placed through `edit.json` or the editor.
- Start HyperFrames work with the `/hyperframes:hyperframes` skill, in `projects/<name>/` of that repo. Copy
  fonts and sounds from `library/` into the project's `assets/` (Amharic needs an `@font-face` to a library
  Ethiopic font). Keep one look across both engines: same fonts, colours and paper textures.
- Real 3D scenes (a desk, a room, a product, camera moves with depth of field): the `3d-animator` skill
  (three.js rendered frame by frame, no Blender; installed 2026-11-22 from a shared zip, reviewed). Its render
  is an MP4 that joins the video like any other clip. Install with `PUPPETEER_SKIP_DOWNLOAD=1 npm install` and
  set `CHROME_PATH` to the installed Chrome. Its ElevenLabs voice and sound steps cost money: use `narrate`
  and the library sounds instead unless the user says otherwise.
- Never use HyperFrames' paid parts (cloud render, HeyGen sign-in, Pro templates, `reverse-any-video`,
  `style-sampling`) without asking. Details: that repo's `README.md`.

## Folders
| Folder | What |
|---|---|
| `projects/<name>/` | one folder per video: `inbox` (drop anything here), footage, stills, maps, refs, voice, music, docs, captions, kit, exports, `brief.md`, `project.json` |
| `projects/<name>/kit/` | library assets picked for this video (import this folder into CapCut/Resolve) |
| `library/` | royalty-free assets + `index.html` browser (`studio library`) + README |
| `library/sfx`, `music`, `overlays`, `transitions`, `backgrounds`, `textures`, `luts` | generated locally, free to use |
| `library/graphics/`, `library/motion/` | transparent PNG graphics / animated overlays from Motion Studio |
| `library/fonts/` | open-licensed typefaces; `studio fonts` installs them for editor titles |
| `library/user-sfx`, `user-music`, `user-footage` | your own downloads (keep a `LICENSES.txt`) |
| `library/powergrades/` | downloaded .drx PowerGrades (Resolve) |
| `library/ai-generated/` | images/clips generated with Higgsfield |
| `library/footage/obs/` | OBS recordings (vertical 1080x1920: app screen, talking head, voiceover) |
| `LUTs/`, `previews/`, `captions/` | generated by the tools |
| `bridge/` | connection to Resolve (don't edit) |
| `models/` | local speech model for captions |

## Rules for the AI (Claude, follow these)
- Videos are vertical 9:16 unless the user says otherwise: prefer `-9x16` assets.
- One video per request: the vertical one. No other shapes (16:9) and no alternate versions unless the user asks
  for them. Pictures the user supplies or points to (memes, Pinterest, screenshots) are used as they are: do not
  build licence-clean stand-ins and do not raise picture licences in reports unless asked (the user's call,
  2026-11-21). Tools that record a source automatically keep doing so quietly.
- Every video ends with the credit "Edit by Cheri" (end card or final seconds). Check a last frame for it.
- Captions should vary from line to line (size, emphasis, entrance); never the same pill for every line.
- Sound effects: vary them and keep whooshes rare (the user finds whoosh-on-everything tiresome). Use the
  tactile set for most cues: clicks, taps, stamp-thunk, paper-slide, page-turn, pen-scribble,
  marker-stroke, typewriter keys, plucks, tiny bells (`library_search tactile`). Rotate within a role and
  never use the same sound on consecutive cues.
- Resolve only: check `bridge_status` first. Grades: always `apply_grade` dry run first, then confirm=true.
  They go into the 'resolve-assist' grade version; `undo_grade` restores. The user allowed applying grades
  without asking each time after an initial yes in a session, but still report what was done.
- Resolve only: edits (music, titles, captions, formats) only on '(resolve-assist)' timeline copies; never
  delete or change the user's original timelines.
- CapCut has no scripting: never claim something was changed in CapCut. Prepare files, then say exactly
  where to click (Import, Captions → Import file, Adjustment → LUT, Blend mode).
- Prefer library assets (`library_search`) over downloads; mention licenses for user-added assets.
- Report honestly: say when something failed or was approximated (e.g. look as CDL instead of LUT).
- Higgsfield spends the user's credits (Basic plan): always run `higgsfield generate cost ...` first,
  state the cost and remaining balance (`higgsfield account status`), and wait for an OK.
  Save results to `library/ai-generated/` and run `library_build` to index them.
- After adding files to `library/`, run `library_build` so `library_search`/`import_assets` see them.
- To continue an edit in CapCut or Resolve: `handoff` exports the project's `edit.json` as separate layers
  (clips, transparent text, stems, looks, OTIO/FCPXML, README). Tell the user it is a rebuild kit, not a
  CapCut project file.
- Narration: `narrate` turns a script into voice audio with word and cue timings (put `{cue}` markers
  before the words that should trigger visuals). Tell the user that the natural voices send the script
  text to Microsoft; the local voice does not.
- Real pictures: `commons_search` then `commons_add` (licence recorded automatically). Prefer public
  domain / CC0; report attribution and share-alike notes. For anything else use `project_credit`.
- Pictures with depth: `project_cutout` splits a project picture into subject and filled background
  (`stills/layers/`); Motion Studio's `DeskStory` photo tiles move the two against each other. macOS only.
- Talking-head clips: `edit_prep` (cut silences, word transcript) → `edit_plan` with your scene
  recommendations → the user picks scenes in `projects/<name>/prep/plan.html` and pastes the plan back →
  build with Motion Studio's `MinimalStory` → revisions → sound design last. Use the
  `minimal-talking-head` skill; never skip the user's planning step.
- Recording (OBS): `obs_status` first; start a recording only when the user asks (it captures their
  screen/camera/mic). `obs_stop_recording` returns the file and indexes it; then `import_assets` or a kit.
"""

PROJECT_NOTES = """# {name}

- Created: {date}
- Format: 9x16 (Reels / TikTok / Shorts)
- Editor: (resolve / capcut)
- Music: (file in music/, license)
- Look: (e.g. golden-hour 60%)

## Shot list / ideas

## To do
- [ ] Import footage into your editor (drag the footage/ folder in; kit/ holds the picked library assets)
- [ ] Grade
- [ ] Cut (match cuts / beat)
- [ ] Captions
- [ ] Export to exports/
"""


def init_workspace() -> dict:
    root = output_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(exist_ok=True)
    guide = root / "CLAUDE.md"
    guide.write_text(WORKSPACE_GUIDE, encoding="utf-8")
    (root / "README.md").write_text(WORKSPACE_GUIDE, encoding="utf-8")
    (root / "AGENTS.md").write_text(WORKSPACE_GUIDE, encoding="utf-8")   # the same guide for Codex
    return {"workspace": str(root), "guide": str(guide)}


def new_project(name: str) -> dict:
    import time
    clean = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip()[:60]
    if not clean:
        raise ValueError("give the project a name (letters, numbers, spaces, - or _)")
    init_workspace()
    root = output_dir() / "projects" / clean
    for d in PROJECT_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    notes = root / "notes.md"
    if not notes.exists():
        notes.write_text(PROJECT_NOTES.format(name=clean, date=time.strftime("%Y-%m-%d")), encoding="utf-8")
    return {"project": str(root), "folders": list(PROJECT_DIRS),
            "next": "Copy your footage into footage/. Resolve: File → New Project, drag footage/ into the Media "
                    "Pool and ask for a 9x16 timeline. CapCut: New project (9:16) → Import → footage/ and kit/."}


PROJECT_BRIEF = """# Brief: {name}

Fill in what you know; Claude reads this first in every session and adds to the log at the bottom,
so nothing has to be explained or decided twice.

- Goal of the video:
- Audience / platform: (Reels, TikTok, Shorts…)
- Length and format: 9x16, ~30 s
- Style kit: (minimal-talking-head / vox / promo / none)
- Editor: (resolve / capcut / in-app)
- Must use: (clips, logo, colours, music)
- Call to action:

## Notes for the edit

## Decisions and progress (newest first)
"""

_VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}
_AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".flac"}
_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".heic", ".svg", ".gif"}
_DOCS = {".txt", ".md", ".pdf", ".docx", ".srt", ".json", ".csv", ".rtf"}


def _sort_folder(name: str, ext: str) -> str | None:
    """Where a dropped file belongs. File names steer it: 'map', 'ref', 'voice' and friends."""
    low = name.lower()
    if ext in _VIDEO:
        return "refs" if re.search(r"\b(ref|reference|inspo|example)", low) else "footage"
    if ext in _AUDIO:
        return "voice" if re.search(r"(voice|narration|\bvo\b|voiceover|interview)", low) else "music"
    if ext in _IMAGE:
        if "map" in low:
            return "maps"
        return "refs" if re.search(r"\b(ref|reference|inspo|moodboard|screenshot)", low) else "stills"
    return "docs" if ext in _DOCS else None


def project_intake(project: str) -> dict:
    """Sort everything in projects/<project>/inbox/ into footage, stills, maps, refs, voice, music, docs
    (moved inside the project, never overwritten), then refresh the project index."""
    proj = Path(new_project(project)["project"])
    moved, left = [], []
    for f in sorted((proj / "inbox").rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        folder = _sort_folder(f.name, f.suffix.lower())
        if folder is None:
            left.append(f.name)
            continue
        dst = proj / folder / f.name
        n = 1
        while dst.exists():
            dst = proj / folder / f"{f.stem}-{n}{f.suffix}"
            n += 1
        shutil.move(str(f), str(dst))
        moved.append(f"{folder}/{dst.name}")
    index = project_index(project)
    return {"project": str(proj), "moved": moved, "left_in_inbox": left, **{k: index[k] for k in ("counts", "new", "index")}}


def project_index(project: str) -> dict:
    """Write projects/<project>/project.json: every file with kind, size, duration and dimensions, plus
    which preparation results exist. Unchanged files are not measured again (size + time match)."""
    import time
    proj = Path(new_project(project)["project"])
    path = proj / "project.json"
    try:
        old = {e["file"]: e for e in json.loads(path.read_text(encoding="utf-8")).get("files", [])}
    except (OSError, json.JSONDecodeError, KeyError):
        old = {}
    kinds = {"footage": "video", "stills": "image", "maps": "map", "refs": "reference", "voice": "voice",
             "music": "music", "docs": "document", "captions": "captions", "exports": "export"}
    files, new = [], []
    for folder, kind in kinds.items():
        for f in sorted((proj / folder).rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = f.relative_to(proj).as_posix()
            st = f.stat()
            prev = old.get(rel)
            if prev and prev.get("bytes") == st.st_size and prev.get("mtime") == int(st.st_mtime):
                files.append(prev)
                continue
            entry = {"file": rel, "kind": kind, "bytes": st.st_size, "mtime": int(st.st_mtime)}
            for k in CREDIT_KEYS:                       # a credit belongs to the file, not to one version of it
                if prev and prev.get(k):
                    entry[k] = prev[k]
            if f.suffix.lower() in _VIDEO | _AUDIO | (_IMAGE - {".svg"}):
                try:
                    from .analysis.video import probe
                    info = probe(f)
                    for k in ("duration", "width", "height", "fps"):
                        if info.get(k):
                            entry[k] = round(info[k], 3) if isinstance(info[k], float) else info[k]
                except Exception:
                    pass
            files.append(entry)
            new.append(rel)
    brief = proj / "brief.md"
    if not brief.exists():
        brief.write_text(PROJECT_BRIEF.format(name=proj.name), encoding="utf-8")
    prep = sorted(p.name for p in (proj / "prep").glob("*.prep.json")) if (proj / "prep").is_dir() else []
    counts: dict[str, int] = {}
    for e in files:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    data = {"name": proj.name, "updated": time.strftime("%Y-%m-%d %H:%M"), "editor": preferred_editor(),
            "counts": counts, "prepared": prep, "has_plan": (proj / "prep" / "plan.html").exists(),
            "has_edit": (proj / "edit.json").exists(), "files": files}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    _write_credits(proj, files)
    return {"index": str(path), "brief": str(brief), "counts": counts, "new": new, "prepared": prep}


CREDIT_KEYS = ("source", "license", "author")


def _write_credits(proj: Path, files: list[dict]) -> None:
    """CREDITS.md: every third-party file with its source and licence (generated; edit via project_credit)."""
    rows = [f for f in files if any(f.get(k) for k in CREDIT_KEYS)]
    if not rows:
        return
    lines = [f"# Credits: {proj.name}", "", "Generated from project.json. Third-party material used in this video.", "",
             "| File | Licence | Author | Source |", "|---|---|---|---|"]
    lines += [f"| `{f['file']}` | {f.get('license', '')} | {f.get('author', '')} | {f.get('source', '')} |" for f in rows]
    warn = [f["file"] for f in rows if "sa" in re.split(r"[\s-]+", str(f.get("license", "")).lower())]
    if warn:
        lines += ["", "Share-alike licences apply to: " + ", ".join(f"`{x}`" for x in warn)
                  + ". A video using them may have to be published under the same licence."]
    (proj / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def project_credit(project: str, file: str, source: str = "", license: str = "", author: str = "") -> dict:
    """Record where a project file came from and under which licence (kept in project.json, listed in CREDITS.md)."""
    proj = Path(new_project(project)["project"])
    project_index(project)
    path = proj / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = next((e for e in data["files"] if e["file"] == file or Path(e["file"]).name == file), None)
    if entry is None:
        raise ValueError(f"no such file in the project: {file}")
    for k, v in (("source", source), ("license", license), ("author", author)):
        v = " ".join(str(v).split())[:300]
        if v:
            entry[k] = v
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    _write_credits(proj, data["files"])
    return {"file": entry["file"], **{k: entry.get(k, "") for k in CREDIT_KEYS}, "credits": str(proj / "CREDITS.md")}


def commons_add(project: str, title: str, name_hint: str = "") -> dict:
    """Download an image from Wikimedia Commons into the project (stills, or maps when the name says map)
    with its licence, author and source recorded."""
    from . import commons
    proj = Path(new_project(project)["project"])
    folder = "maps" if "map" in (name_hint or title).lower() else "stills"
    got = commons.fetch(title, proj / folder)
    rel = Path(got["path"]).relative_to(proj).as_posix()
    project_index(project)
    credit = project_credit(project, rel, got["source"], got["license"], got["author"])
    notes = []
    if got["share_alike"]:
        notes.append("Share-alike licence: a video using this image may have to be published under the same licence.")
    elif got["attribution"]:
        notes.append("Attribution required: credit the author in the video or its description.")
    elif not got["free"]:
        notes.append("Licence is not clearly free: check the source page before using it.")
    return {**credit, "notes": notes}


PLATES_DIR = Path(__file__).resolve().parents[2] / "tools" / "plates"


def _plates_tool(name: str) -> Path:
    """Path of a picture helper (tools/plates), built on first use. macOS only: it uses Apple's Vision framework."""
    import subprocess
    if sys.platform != "darwin":
        raise RuntimeError("subject cut-outs need macOS (they use Apple's Vision framework)")
    src, exe = PLATES_DIR / f"{name}.swift", PLATES_DIR / "bin" / name
    if not src.is_file():
        raise RuntimeError(f"the picture helpers are missing: {src}")
    if not exe.is_file() or exe.stat().st_mtime < src.stat().st_mtime:
        if not shutil.which("swiftc"):
            raise RuntimeError("building the picture helpers needs the Xcode command line tools (run: xcode-select --install)")
        exe.parent.mkdir(exist_ok=True)
        done = subprocess.run(["swiftc", "-O", str(src), "-o", str(exe)], capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            raise RuntimeError(f"could not build {name}: {done.stderr.strip()[-400:]}")
    return exe


def _run_subject(picture: Path, out_dir: Path, stem: str, options: list[str]) -> str:
    import subprocess
    done = subprocess.run([str(_plates_tool("subject")), str(picture), str(out_dir), stem, *options], capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-400:] or "no subject found in the picture")
    return done.stdout


def project_cutout(project: str, file: str, roi: str = "", fill_black: bool = False, pick: str = "all") -> dict:
    """Cut the subject out of a project picture: writes stills/layers/<name>-fg.png (subject, transparent),
    -bg.png (subject removed, hole filled in) and -mask.png, with the picture's credit carried over."""
    proj = Path(new_project(project)["project"])
    project_index(project)
    data = json.loads((proj / "project.json").read_text(encoding="utf-8"))
    entry = next((e for e in data["files"] if e["file"] == file or Path(e["file"]).name == file), None)
    if entry is None:
        raise ValueError(f"no such file in the project: {file}")
    picture = proj / entry["file"]
    if picture.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"):
        raise ValueError("a cut-out needs a picture (jpg, png, webp, heic or tiff)")
    options: list[str] = []
    if roi:
        try:
            box = [float(v) for v in roi.split(",")]
        except ValueError:
            box = []
        if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise ValueError("roi is x0,y0,x1,y1 as fractions of the picture, for example 0.5,0.3,1,0.95")
        options += ["--roi", ",".join(f"{v:.4f}" for v in box)]
    if not re.fullmatch(r"all|\d+(,\d+)*", pick):
        raise ValueError("pick is 'all' or subject numbers like 1,3")
    options += ["--pick", pick]
    if fill_black:
        options += ["--fill-black", "--black-max", "6", "--fade", "90"]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", picture.stem).strip("-").lower()[:60] or "picture"
    out_dir = proj / "stills" / "layers"
    out_dir.mkdir(parents=True, exist_ok=True)
    found = [line.strip() for line in _run_subject(picture, out_dir, stem, options).splitlines() if line.startswith("instance")]
    project_index(project)
    made = {"subject": f"stills/layers/{stem}-fg.png", "background": f"stills/layers/{stem}-bg.png", "mask": f"stills/layers/{stem}-mask.png"}
    if any(entry.get(k) for k in CREDIT_KEYS):                   # the layers are the same picture: same licence and author
        for rel in made.values():
            project_credit(project, rel, f"made here from {entry['file']}" + (f" ({entry['source']})" if entry.get("source") else ""),
                           entry.get("license", ""), entry.get("author", ""))
    return {**made, "found": found, "next": "tools/plates/bin/plate composes these for a frame shape (see tools/plates/README.md); "
            "Motion Studio DeskStory photo tiles take them as picture.src and picture.fg"}


def project_narrate(project: str, text: str, name: str = "narration", voice: str | None = None, rate: str = "+0%",
                    provider: str = "auto") -> dict:
    """Script -> voice audio in projects/<project>/voice/ and word/cue timings in prep/<name>.narration.json."""
    from .narration import narrate
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:40] or "narration"
    proj = Path(new_project(project)["project"])
    res = narrate(text, proj / "voice" / f"{clean}.wav", proj / "prep" / f"{clean}.narration.json", voice, rate, provider)
    (proj / "docs").mkdir(exist_ok=True)
    (proj / "docs" / f"{clean}.script.txt").write_text(text.strip() + "\n", encoding="utf-8")
    project_index(project)
    return res


def preferred_editor() -> str:
    """The user's default editor: 'resolve', 'capcut' or 'none' (~/.config/studio/config, STUDIO_EDITOR)."""
    import os
    env = os.environ.get("STUDIO_EDITOR", "").strip().lower()
    if env in EDITORS:
        return env
    try:
        for line in (Path.home() / ".config" / "studio" / "config").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "editor" and value.strip().lower() in EDITORS:
                return value.strip().lower()
    except OSError:
        pass
    return "resolve"


def project_kit(project: str, queries: list[str], per_query: int = 1) -> dict:
    """Copy the best library match for each query into projects/<project>/kit/ (for editors without
    a bridge, e.g. CapCut: import that one folder). Files are copied, never moved."""
    from .library.build import library_dir, search
    if not 1 <= len(queries) <= 40:
        raise ValueError("give 1..40 search phrases, e.g. ['whoosh', 'warm light leak 9:16', 'uplift music']")
    proj = Path(new_project(project)["project"])
    kit = proj / "kit"
    lib = library_dir().resolve()
    copied, missing = [], []
    for q in queries:
        hits = search(str(q), None, max(1, min(5, int(per_query))))
        if not hits:
            missing.append(q)
        for it in hits:
            src = (lib / it["file"]).resolve()
            if lib not in src.parents or not src.is_file():
                continue
            dst = kit / it["category"].replace("/", "-") / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)
            copied.append({"query": q, "id": it["id"], "file": str(dst.relative_to(proj)), "usage": it["usage"]})
    return {"kit": str(kit), "copied": copied, "not_found": missing,
            "next": "Import the kit folder into your editor (CapCut: Import → select the kit folder)."}


def doctor() -> dict:
    """Check every piece and say exactly what to fix."""
    from .bridge import PROTOCOL, Bridge, bridge_dir
    from .captions import MODELS, find_whisper, models_dir
    from .library.build import library_dir, load_manifest

    checks = []

    def check(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, **({"fix": fix} if not ok and fix else {})})

    check("python", sys.version_info >= (3, 10), sys.version.split()[0], "Install Python 3.10+")
    check("resolve-assist", True, __version__)
    editor = preferred_editor()
    check("editor", True, f"{editor} (change with: studio editor resolve|capcut|none)")
    if editor == "capcut":
        capcut = Path("/Applications/CapCut.app").exists()
        check("CapCut", capcut, "installed" if capcut else "missing", "Install CapCut from capcut.com or the App Store")
    resolve_app = Path("/Applications/DaVinci Resolve.app")
    store = (resolve_app / "Contents/_MASReceipt").exists()
    check("DaVinci Resolve", resolve_app.exists(), "App Store build (sandboxed)" if store else "installed",
          "Install DaVinci Resolve")
    ff = find_ffmpeg()
    check("ffmpeg", bool(ff), ff or "missing", "brew install ffmpeg (needed for video, captions, transitions)")
    wh = find_whisper()
    check("whisper.cpp", bool(wh), wh or "missing", "brew install whisper-cpp (needed for captions)")
    models = [n for n, (f, _mb) in MODELS.items() if (models_dir() / f).is_file()]
    check("caption model", bool(models), ", ".join(models) or "none", "resolve-assist captions <file> downloads it")
    items = load_manifest().get("items", [])
    cats = sorted({i["category"] for i in items})
    check("asset library", len(items) >= 50, f"{len(items)} assets ({', '.join(cats)})" if items else "not built",
          "resolve-assist library")
    check("library transitions", "transitions" in cats, "present" if "transitions" in cats else "missing",
          "Install ffmpeg, then: resolve-assist library")
    bridge_file = bridge_dir() / "bridge.lua"
    installed = bridge_file.exists() and f"local PROTOCOL = {PROTOCOL}" in bridge_file.read_text(encoding="utf-8")
    check("bridge installed", installed, f"protocol {PROTOCOL}" if installed else "missing or outdated",
          "resolve-assist bridge-install")
    st = Bridge().status()
    running_proto = st.get("protocol")
    if st.get("running"):
        same = running_proto == PROTOCOL
        check("bridge running", same, f"protocol {running_proto}" + ("" if same else f" (installed: {PROTOCOL})"),
              "Restart it: resolve-assist bridge-stop, then Workspace → Scripts → Utility → resolve-assist Bridge")
    else:
        check("bridge running", False, "not running",
              "In Resolve: Workspace → Scripts → Utility → resolve-assist Bridge")
    claude_cfg = Path.home() / ".claude.json"
    registered = False
    try:
        registered = "resolve-assist" in json.dumps(json.loads(claude_cfg.read_text(encoding="utf-8")).get("mcpServers", {}))
    except (OSError, json.JSONDecodeError):
        pass
    check("Claude Code connection", registered, "registered" if registered else "not registered",
          "claude mcp add --scope user resolve-assist -- <repo>/.venv/bin/resolve-assist-mcp")
    check("workspace guide", (output_dir() / "CLAUDE.md").exists(), str(output_dir() / "CLAUDE.md"),
          "resolve-assist workspace")
    from .obs import password_file
    obs_app = Path("/Applications/OBS.app").exists()
    obs_ok = obs_app and password_file().is_file()
    check("OBS (recording)", obs_ok, "installed, WebSocket password file present" if obs_ok else
          ("password file missing" if obs_app else "not installed"),
          "brew install --cask obs, then follow docs/OBS.md (WebSocket password file)")
    free = shutil.disk_usage(output_dir() if output_dir().exists() else Path.home()).free / 1e9
    check("disk space", free > 20, f"{free:.0f} GB free", "Free up space: video work needs 20 GB+")
    optional = {"bridge running", "OBS (recording)"}
    if editor != "resolve":                       # Resolve is not needed for a CapCut / file-only workflow
        optional |= {"DaVinci Resolve", "bridge installed"}
    if editor != "resolve":                       # don't nag about a bridge that isn't part of this workflow
        checks = [c for c in checks if c["check"] not in ("bridge running", "bridge installed")]
    return {"ready": all(c["ok"] for c in checks if c["check"] not in optional),
            "editor": editor, "checks": checks, "library": str(library_dir())}
