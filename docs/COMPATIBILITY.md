# Compatibility

| Component | Tested | Notes |
|---|---|---|
| Python | 3.10 (CI), 3.15.2 (dev) | Core is stdlib-only |
| macOS | dev machine | sips fallback available |
| Linux | CI | ffmpeg or built-in PNG decoder |
| Resolve Free 21.2.0 (macOS) | **pending probe** | Fill in from `probe-report` |

## Mac App Store build (found 2026-11-16)

The dev machine runs the **Mac App Store** build (`com.blackmagic-design.DaVinciResolveLite`), which is sandboxed:

- It does **not** read `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts`; its Scripts menu shows only Comp/Edit/Color/Deliver.
- Its files live in `~/Library/Containers/com.blackmagic-design.DaVinciResolveLite/`, which other apps (Terminal) may not read or write.
- Workaround: paste the probe into Workspace → Console (Lua). The probe writes to `~/Movies/resolve-assist` or `~/Pictures/resolve-assist` when the sandbox allows it, and always prints its JSON to the console.
- Phase 2 (the bridge) depends on which folders the sandbox can share; the non-App-Store download from blackmagicdesign.com avoids this.

## Known platform facts (as of 2026-11)

- Resolve 21.1+ Free: external scripting and the built-in MCP server are Studio-only;
  Python scripts are not offered in the Free Workspace → Scripts menu; Lua scripts run.
- Resolve Free loads `.cube` LUTs on any node.

## Probe results

_Add one section per Resolve version: date, product/version, Lua libraries available,
whether `io` works, which color methods exist (`SetCDL`, `SetLUT`, `GetNodeGraph` ...),
and the method-existence control result._
