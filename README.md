# resolve-assist

A local AI color assistant for **DaVinci Resolve Free**. It measures your footage,
suggests corrections, matches shots, and writes `.cube` LUTs that Resolve Free can load.
It works with Claude (or any MCP client) or from the command line.

- 🔒 **Local only.** No uploads, no telemetry. The core uses only the Python standard library.
- 🛡️ **Can't damage your project.** v0.1 only *reads* your stills and *writes* LUT files.
- 🧯 **Fallbacks everywhere.** ffmpeg → macOS `sips` → built-in PNG decoder.

> Status: v0.1 (Phase 0 + 1). Direct "apply to clip inside Resolve" is Phase 2.
> See [PROJECT.md](PROJECT.md) for goals, architecture, security and roadmap.

## Install

```bash
git clone https://github.com/Cherireal7/resolve-assist.git
cd resolve-assist
python3 -m venv .venv
.venv/bin/pip install -e ".[mcp]"
.venv/bin/resolve-assist status
```

Optional: `brew install ffmpeg` lets it read video files and every image format.
Without ffmpeg, PNG/TIFF/JPEG stills still work.

### Connect to Claude Code

```bash
claude mcp add resolve-assist -- "$PWD/.venv/bin/resolve-assist-mcp"
```

## Workflow

1. In Resolve: Color page → right-click the viewer → **Grab Still**. In the Gallery,
   right-click the still → **Export** → PNG (or TIFF).
2. Ask Claude: *"Analyze ~/Desktop/shot1.png and balance it, then add the warm-film look at 50%."*
3. Claude runs `analyze_frame` → `suggest_balance` → `render_preview`, shows you a
   before/after, and runs `make_lut`.
4. In Resolve: Project Settings → Color Management → **Open LUT Folder** → copy the `.cube`
   there (or use `install_to_resolve`) → **Update Lists** → right-click a node → **LUT**.

## CLI

```bash
resolve-assist analyze shot.png
resolve-assist balance shot.png
resolve-assist match shotB.png shotA.png
resolve-assist looks
resolve-assist lut "Shot1 warm" --look warm-film --strength 0.6 --slope "1.05 1 0.95"
resolve-assist preview shot.png shot1 --look teal-orange
resolve-assist install-probe     # adds a read-only probe to Resolve's Scripts menu
resolve-assist probe-report
```

## MCP tools

| Tool | What it does |
|---|---|
| `environment_status` | Available decoders, folders, probe status |
| `analyze_frame` | Exposure, contrast, cast, clipping, saturation, warnings, confidence |
| `suggest_balance` | Neutral correction as CDL, verified by re-measuring |
| `match_shots` | CDL that matches one shot to another |
| `list_looks` | Built-in looks: warm-film, teal-orange, cool-night, bleach-bypass, clean-commercial, bw-contrast |
| `render_preview` | Before/after PNG rendered locally |
| `make_lut` | `.cube` (17/33/65) + `.cc` written to `~/Documents/resolve-assist/LUTs` |
| `resolve_probe_report` | What this Resolve install's scripting API allows |

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t tests
```

Docs: [PROJECT.md](PROJECT.md) · [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) ·
[docs/TESTING.md](docs/TESTING.md) · [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)

MIT licensed. Not affiliated with Blackmagic Design.
