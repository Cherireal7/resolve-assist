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
    mm.add_argument("--preset", default="calm-lofi", choices=("calm-lofi", "bright-pop", "ambient"))
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
