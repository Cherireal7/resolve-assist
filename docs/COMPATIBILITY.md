# Compatibility

| Component | Tested | Notes |
|---|---|---|
| Python | 3.10 (CI), 3.15.2 (dev) | Core is stdlib-only |
| macOS | dev machine | sips fallback available |
| Linux | CI | ffmpeg or built-in PNG decoder |
| Resolve Free 21.2.0.6 (macOS, App Store) | probe v1 run 2026-11-16 | Sandboxed; see below |

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

### Free 21.2.0.6, macOS, Mac App Store build: probe v1, 2026-11-16

Run by pasting into Workspace → Console (the Console has no language switch: Lua only).

| Check | Result |
|---|---|
| Runtime | Lua 5.1 / LuaJIT 2.1 |
| `io`, `require`, `debug`, `ffi` | **not available** |
| `os` | available (`getenv`, `date`) |
| `loadstring` | available (we never use it on external data) |
| File helpers | `bmd.writestring`, `bmd.readstring`, `bmd.fileexists`, `bmd.direxists`, `bmd.copyfile` (no `bmd.writefile`/`createdir`) |
| HOME | app container (`~/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data`) |
| Fusion paths | Scripts/LUTs under `<container>/Library/Application Support/Fusion/` |
| Method-existence control | reliable (unknown names return `nil`) |
| Project | `ExportCurrentFrameAsStill`, `GetGallery`, `RefreshLUTList`, `Get/SetSetting`: present |
| Timeline | `GrabStill`, `GrabAllStills`, `GetCurrentVideoItem`, `Export`, `Get/SetCurrentTimecode`: present |
| Clip color methods (`SetCDL`, `SetLUT`, `GetNodeGraph`) | **not checked yet**: playhead was past the last clip |
| Report file | not written (v1 only knew `io`/`bmd.writefile`) → probe v2 uses `bmd.writestring` |

Implications for Phase 2:
- Transport must use `bmd.writestring`/`readstring` (no `io`), polling a shared folder.
- Which folder the sandbox shares with the outside world is tested by probe v2 (`write_tests`).
- `ExportCurrentFrameAsStill` would let the AI grab frames itself (tested by probe v2).
