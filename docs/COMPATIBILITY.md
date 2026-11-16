# Compatibility

| Component | Tested | Notes |
|---|---|---|
| Python | 3.10 (CI), 3.15.2 (dev) | Core is stdlib-only |
| macOS | dev machine | sips fallback available |
| Linux | CI | ffmpeg or built-in PNG decoder |
| Resolve Free 21.2.0.6 (macOS, App Store) | probe v2 run 2026-11-16 | Sandboxed; color API present; see below |

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
| Clip (TimelineItem) | `SetCDL`, `SetLUT`, `GetLUT`, `GetNodeGraph`, `CopyGrades`, `ExportLUT`, `AddVersion`, `LoadVersionByName`, `GetColorGroup`: **present**; `ApplyGradeFromDRX` not on the item (it is on the graph) |
| Node graph | `SetLUT`, `GetLUT`, `ApplyGradeFromDRX`, `ApplyArriCdlLut`, `ResetAllGrades`, `SetNodeEnabled`, `GetNodeLabel`, `GetToolsInNode`: **present** |
| Report file | v2: `bmd.writestring` **blocked** in `~/.resolve-assist`, `~/Movies/…`, `~/Pictures/…` and the container's (non-existent) Movies/Pictures subfolders |

Implications for Phase 2:
- Transport must use `bmd.writestring`/`readstring` (no `io`), polling a shared folder.
- The color API needed for Phase 2 exists: apply LUT (`SetLUT`), CDL (`SetCDL`), PowerGrades (`graph:ApplyGradeFromDRX`), versions for undo (`AddVersion`/`LoadVersionByName`).
- `bmd.writestring`/`readstring` are **serializers, not file I/O** (writestring returns the quoted string); probe v2 write tests were therefore invalid.
- `project:ExportCurrentFrameAsStill("~/Documents/resolve-assist/bridge/frame.png")` **works** in the sandbox (1920×1080 PNG written).
- File I/O without `io`: Fusion's `fu:OpenFile(path, 1=read|2=write)` with `ReadLine`/`WriteLine`/`Flush`/`Close`; test pending.
- Blocker: a folder both Resolve (sandboxed) and our server can use. Next test: `~/Documents/resolve-assist/bridge` and the container `tmp/`;
  if blocked, grant access by adding the folder in Resolve (Preferences → Media Storage) so the sandbox gets a user-approved bookmark.
