"""Command line: same features as the MCP server, works without the mcp SDK."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, api


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="resolve-assist", description="Color assistant for DaVinci Resolve Free")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show environment and folders")

    a = sub.add_parser("analyze", help="measure a still or video frame")
    a.add_argument("path")
    a.add_argument("--time", type=float)

    b = sub.add_parser("balance", help="suggest a neutral correction")
    b.add_argument("path")
    b.add_argument("--time", type=float)
    b.add_argument("--no-exposure", action="store_true")

    m = sub.add_parser("match", help="match SOURCE to REFERENCE")
    m.add_argument("source")
    m.add_argument("reference")
    m.add_argument("--strength", type=float, default=1.0)

    sub.add_parser("looks", help="list built-in looks")

    def grade_args(sp):
        sp.add_argument("--look")
        sp.add_argument("--strength", type=float, default=1.0)
        sp.add_argument("--slope", default="1 1 1")
        sp.add_argument("--offset", default="0 0 0")
        sp.add_argument("--power", default="1 1 1")
        sp.add_argument("--saturation", type=float, default=1.0)

    lut = sub.add_parser("lut", help="write a .cube LUT")
    lut.add_argument("name")
    grade_args(lut)
    lut.add_argument("--size", type=int, default=33, choices=(17, 33, 65))
    lut.add_argument("--install", action="store_true", help="copy into Resolve's LUT folder")
    lut.add_argument("--overwrite", action="store_true")

    pv = sub.add_parser("preview", help="before/after PNG")
    pv.add_argument("path")
    pv.add_argument("name")
    grade_args(pv)
    pv.add_argument("--time", type=float)

    sub.add_parser("install-probe", help="install the read-only probe into Resolve's Scripts menu")
    sub.add_parser("probe-report", help="show the probe result")
    bi = sub.add_parser("bridge-install", help="install the live bridge and copy its starter to the clipboard")
    bi.add_argument("--no-copy", action="store_true")
    sub.add_parser("bridge-status", help="is the bridge running in Resolve?")
    sub.add_parser("bridge-stop", help="stop the bridge in Resolve")
    sub.add_parser("clips", help="list clips on the current timeline")
    g = sub.add_parser("grab", help="grab + analyze a frame from Resolve")
    g.add_argument("target", nargs="?", default="current")
    ap = sub.add_parser("apply", help="apply a grade to a clip in Resolve (dry run unless --yes)")
    ap.add_argument("target", nargs="?", default="current")
    grade_args(ap)
    ap.add_argument("--node", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="really apply (otherwise only show the plan)")
    st = sub.add_parser("stabilize", help="run Resolve's stabilizer on a clip")
    st.add_argument("target", nargs="?", default="current")
    mm = sub.add_parser("make-music", help="generate royalty-free preset music")
    from .audio import PRESETS as _music_presets
    mm.add_argument("--preset", default="calm-lofi", choices=tuple(_music_presets))
    mm.add_argument("--seconds", type=float)
    mu = sub.add_parser("music", help="add music from ~/Documents/resolve-assist/media (on a timeline copy)")
    mu.add_argument("file")
    ti = sub.add_parser("title", help="add a Text+ title (on a timeline copy); | = new line")
    ti.add_argument("text")
    ti.add_argument("--at", type=float, default=0.0, help="seconds from the start")
    ti.add_argument("--duration", type=float, default=5.0)
    ti.add_argument("--target", default="1:1")
    sub.add_parser("reset-copy", help="delete the resolve-assist timeline copy (never the original)")
    un = sub.add_parser("undo", help="restore the clip's previous grade version")
    un.add_argument("target", nargs="?", default="current")
    av = sub.add_parser("video", help="shots, best frames, match cuts, contact sheet (needs ffmpeg)")
    av.add_argument("path")
    av.add_argument("--fps", type=float, default=4.0)
    am = sub.add_parser("beats", help="tempo and beats of music or a video's soundtrack")
    am.add_argument("path")
    bp = sub.add_parser("beat-plan", help="beat-synced cut list from videos + music")
    bp.add_argument("music")
    bp.add_argument("videos", nargs="+")
    bp.add_argument("--beats-per-cut", type=int, default=2)
    bp.add_argument("--order", choices=("match", "original"), default="match")
    bp.add_argument("--max-seconds", type=float)
    lb = sub.add_parser("library", help="build the asset library")
    lb.add_argument("--force", action="store_true")
    ls = sub.add_parser("assets", help="search the asset library")
    ls.add_argument("query", nargs="?", default="")
    ls.add_argument("--category")
    ia = sub.add_parser("import", help="import library assets into Resolve's Media Pool")
    ia.add_argument("names", nargs="+")
    pg = sub.add_parser("powergrade", help="apply a .drx from library/powergrades to a clip")
    pg.add_argument("file")
    pg.add_argument("target", nargs="?", default="current")
    fm = sub.add_parser("format", help="copy the timeline into 9x16 / 4x5 / 1x1 / 16x9")
    fm.add_argument("format", nargs="?", default="9x16", choices=("9x16", "4x5", "1x1", "16x9"))
    cp = sub.add_parser("captions", help="local auto captions (file, or the current timeline)")
    cp.add_argument("path", nargs="?")
    cp.add_argument("--model", default="base", choices=("tiny", "base", "small", "medium"))
    cp.add_argument("--language", default="auto")
    cp.add_argument("--max-chars", type=int, default=32)
    cp.add_argument("--no-resolve", action="store_true")
    ab = sub.add_parser("beat-edit", help="analyze + build a beat/match-cut edit in Resolve")
    ab.add_argument("music")
    ab.add_argument("videos", nargs="+")
    ab.add_argument("--beats-per-cut", type=int, default=2)
    ab.add_argument("--order", choices=("match", "original"), default="match")
    ab.add_argument("--max-seconds", type=float)
    ab.add_argument("--sfx", default="whoosh-medium", help="library SFX on every cut, or 'none'")
    ab.add_argument("--title", default="Beat edit")
    sub.add_parser("obs-status", help="OBS: connected? current scene, recording on/off")
    sub.add_parser("obs-scenes", help="OBS: list scenes")
    osc = sub.add_parser("obs-scene", help="OBS: switch to a scene")
    osc.add_argument("name")
    orc = sub.add_parser("obs-record", help="OBS: start recording (into library/footage/obs)")
    orc.add_argument("--scene", help="switch to this scene first")
    ost = sub.add_parser("obs-stop", help="OBS: stop recording, print the file, index it in the library")
    ost.add_argument("--no-index", action="store_true", help="don't refresh the library index")
    dr = sub.add_parser("doctor", help="check the whole setup and show fixes")
    dr.add_argument("--json", action="store_true", help="machine-readable output (used by the Tibeb app)")
    ep = sub.add_parser("prep", help="talking-head clip: transcript, cut silences, script segments, planning page")
    ep.add_argument("video")
    ep.add_argument("project")
    ep.add_argument("--min-silence", type=float, default=0.4)
    ep.add_argument("--padding", type=float, default=0.03)
    ep.add_argument("--model", default="base")
    ep.add_argument("--language", default="auto")
    ep.add_argument("--no-render", action="store_true")
    cd = sub.add_parser("capcut-draft", help="EXPERIMENTAL: write a new CapCut project from a project's hand-off")
    cd.add_argument("project")
    cd.add_argument("--styled-text", action="store_true", help="put the styled text clips on the timeline instead of editable CapCut text")
    crm = sub.add_parser("capcut-remove", help="delete CapCut projects this tool created (never others)")
    crm.add_argument("name", nargs="?")
    cp = sub.add_parser("capcut-pull", help="show what was changed in a CapCut project we created (use --apply to update edit.json)")
    cp.add_argument("name")
    cp.add_argument("--apply", action="store_true")
    sub.add_parser("capcut-list", help="CapCut projects this tool created")
    ci = sub.add_parser("capcut-inspect", help="summarise a CapCut project on disk")
    ci.add_argument("name")
    ho = sub.add_parser("handoff", help="export a project's edit as layers for CapCut / Resolve / any editor")
    ho.add_argument("project")
    ho.add_argument("--format", default="9x16", choices=("9x16", "16x9"))
    ho.add_argument("--motion-dir")
    na = sub.add_parser("narrate", help="script file -> narration audio + word and cue timings in a project")
    na.add_argument("project")
    na.add_argument("script", help="text file; blank lines = pauses, {cue} markers before words")
    na.add_argument("--name", default="narration")
    na.add_argument("--voice")
    na.add_argument("--rate", default="+0%")
    na.add_argument("--provider", default="auto", choices=("auto", "edge", "say"))
    cs = sub.add_parser("commons", help="search Wikimedia Commons, or add an image to a project with its licence")
    cs.add_argument("query", help="search words, or with --add the file title / page URL")
    cs.add_argument("--add", metavar="PROJECT")
    cr = sub.add_parser("credit", help="record source/licence/author for a project file")
    cr.add_argument("project")
    cr.add_argument("file")
    cr.add_argument("--source", default="")
    cr.add_argument("--license", default="")
    cr.add_argument("--author", default="")
    pk = sub.add_parser("peaks", help="waveform outline (and beats) of an audio or video file, as JSON")
    pk.add_argument("path")
    pk.add_argument("--per-second", type=int, default=40)
    pk.add_argument("--beats", action="store_true")
    sub.add_parser("look-curves", help="built-in looks as tone curves + saturation, as JSON")
    it = sub.add_parser("intake", help="sort projects/<project>/inbox into typed folders and index the project")
    it.add_argument("project")
    kt = sub.add_parser("kit", help="copy library assets into projects/<project>/kit (for CapCut / any editor)")
    kt.add_argument("project")
    kt.add_argument("queries", nargs="+", help="search phrases, one asset each: whoosh 'warm light leak' ...")
    kt.add_argument("--per-query", type=int, default=1)
    sub.add_parser("workspace", help="(re)create the workspace guide in ~/Documents/resolve-assist")
    np_ = sub.add_parser("new-project", help="create a project folder with footage/music/exports/...")
    np_.add_argument("name")
    sub.add_parser("serve", help="run the MCP server (stdio)")

    args = p.parse_args(argv)
    try:
        if args.cmd == "status":
            _print(api.status())
        elif args.cmd == "analyze":
            _print(api.analyze(args.path, args.time))
        elif args.cmd == "balance":
            _print(api.balance(args.path, args.time, fix_exposure=not args.no_exposure))
        elif args.cmd == "match":
            _print(api.match(args.source, args.reference, args.strength))
        elif args.cmd == "looks":
            _print(api.looks())
        elif args.cmd == "lut":
            _print(api.make_lut(args.name, args.look, args.strength, args.slope, args.offset, args.power,
                                args.saturation, args.size, args.install, args.overwrite))
        elif args.cmd == "preview":
            _print(api.preview(args.path, args.name, args.look, args.strength, args.slope, args.offset,
                               args.power, args.saturation, args.time))
        elif args.cmd == "install-probe":
            _print(api.install_probe())
        elif args.cmd == "probe-report":
            _print(api.probe_report())
        elif args.cmd == "bridge-install":
            res = api.bridge_install(not args.no_copy)
            print(res["loader"])
            print("Copied to clipboard." if res["loader_copied_to_clipboard"] else "Copy the code above.")
            print(res["next"])
        elif args.cmd == "bridge-status":
            _print(api.bridge_status())
        elif args.cmd == "bridge-stop":
            _print(api.bridge_stop())
        elif args.cmd == "clips":
            _print(api.clips())
        elif args.cmd == "grab":
            _print(api.analyze_clip(args.target))
        elif args.cmd == "apply":
            _print(api.apply_grade(args.target, args.slope, args.offset, args.power, args.saturation,
                                   args.look, args.strength, args.node, confirm=args.yes))
        elif args.cmd == "stabilize":
            _print(api.stabilize(args.target))
        elif args.cmd == "make-music":
            _print(api.make_music(args.preset, args.seconds))
        elif args.cmd == "music":
            _print(api.add_music(args.file))
        elif args.cmd == "title":
            _print(api.add_title(args.text, args.at, args.duration, args.target))
        elif args.cmd == "reset-copy":
            _print(api.reset_copy())
        elif args.cmd == "undo":
            _print(api.undo_grade(args.target))
        elif args.cmd == "video":
            _print(api.analyze_video(args.path, args.fps))
        elif args.cmd == "beats":
            _print(api.analyze_music(args.path))
        elif args.cmd == "beat-plan":
            _print(api.beat_edit_plan(args.videos, args.music, args.beats_per_cut, args.order, args.max_seconds))
        elif args.cmd == "library":
            from .library.build import build_library
            _print(build_library(force=args.force, log=lambda m: print(m, file=sys.stderr)))
        elif args.cmd == "assets":
            res = api.library_search(args.query, args.category)
            for it in res["items"]:
                print(f"{it['category']:12s} {it['id']:28s} {it['usage']}")
            print(f"{res['count']} result(s) in {res['root']}")
        elif args.cmd == "import":
            _print(api.import_assets(args.names))
        elif args.cmd == "powergrade":
            _print(api.apply_powergrade(args.file, args.target))
        elif args.cmd == "format":
            _print(api.make_format(args.format))
        elif args.cmd == "captions":
            if args.path:
                _print(api.captions_for_file(args.path, args.model, args.language, args.max_chars))
            else:
                _print(api.captions_for_timeline(args.model, args.language, args.max_chars, not args.no_resolve))
        elif args.cmd == "beat-edit":
            _print(api.assemble_beat_edit(args.videos, args.music, args.beats_per_cut, args.order,
                                          args.max_seconds, None if args.sfx == "none" else args.sfx, args.title))
        elif args.cmd == "obs-status":
            res = api.obs_status()
            _print(res)
            if not res.get("connected"):
                return 1
        elif args.cmd == "obs-scenes":
            _print(api.obs_scenes())
        elif args.cmd == "obs-scene":
            _print(api.obs_switch_scene(args.name))
        elif args.cmd == "obs-record":
            _print(api.obs_start_recording(args.scene))
        elif args.cmd == "obs-stop":
            _print(api.obs_stop_recording(refresh_library=not args.no_index))
        elif args.cmd == "prep":
            res = api.edit_prep(args.video, args.project, args.min_silence, args.padding, args.model, args.language,
                                not args.no_render)
            res["plan"] = api.edit_plan(args.project)["plan"]
            _print(res)
        elif args.cmd == "capcut-draft":
            _print(api.capcut_draft(args.project, not args.styled_text))
        elif args.cmd == "capcut-remove":
            from . import capcut
            _print(capcut.remove(args.name))
        elif args.cmd == "capcut-pull":
            _print(api.capcut_pull(args.name, args.apply))
        elif args.cmd == "capcut-list":
            from . import capcut
            _print({"drafts": capcut.list_projects()})
        elif args.cmd == "capcut-inspect":
            from . import capcut
            _print(capcut.inspect(args.name))
        elif args.cmd == "handoff":
            _print(api.handoff(args.project, args.format, args.motion_dir))
        elif args.cmd == "narrate":
            from pathlib import Path as _P
            _print(api.narrate(args.project, _P(args.script).read_text(encoding="utf-8"), args.name, args.voice, args.rate, args.provider))
        elif args.cmd == "commons":
            _print(api.commons_add(args.add, args.query) if args.add else api.commons_search(args.query))
        elif args.cmd == "credit":
            _print(api.project_credit(args.project, args.file, args.source, args.license, args.author))
        elif args.cmd == "peaks":
            print(json.dumps(api.media_peaks(args.path, args.per_second, args.beats)))
        elif args.cmd == "look-curves":
            print(json.dumps(api.look_curves()))
        elif args.cmd == "intake":
            _print(api.project_intake(args.project))
        elif args.cmd == "kit":
            _print(api.project_kit(args.project, args.queries, args.per_query))
        elif args.cmd == "doctor":
            res = api.doctor()
            if args.json:
                _print(res)
                return 0
            for c in res["checks"]:
                mark = "✅" if c["ok"] else "❌"
                print(f"{mark} {c['check']:24s} {c['detail']}")
                if not c["ok"] and c.get("fix"):
                    print(f"   → {c['fix']}")
            print("\nREADY" if res["ready"] else "\nSome things need fixing (see →).")
        elif args.cmd == "workspace":
            _print(api.init_workspace())
        elif args.cmd == "new-project":
            _print(api.new_project(args.name))
        elif args.cmd == "serve":
            try:
                from .server import main as serve
            except ImportError:
                print("The MCP SDK is not installed: pip install 'resolve-assist[mcp]'", file=sys.stderr)
                return 2
            serve()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
