# Recording source footage with OBS

OBS Studio captures the raw material (Fida app screen, talking head, voiceover). resolve-assist
controls it over **obs-websocket v5** (built into OBS 28+) with its own small stdlib client, so no
extra Python package is needed. Clips land in the asset library, where `import_assets` brings them
into Resolve.

```
OBS (record) ──▶ ~/Documents/resolve-assist/library/footage/obs/*.mp4 ──▶ library index ──▶ import_assets ──▶ Resolve
```

## Setup (already done on the dev machine, 2026-11-21)

1. `brew install --cask obs`
2. OBS config in `~/Library/Application Support/obs-studio/`:
   - Profile **Vertical 1080x1920**: base and output canvas 1080×1920, 30 fps, Simple output mode,
     **Hybrid MP4** (a normal MP4 at the end that survives an OBS crash), Apple VT H.264 hardware
     encoder at "Indistinguishable quality", AAC audio. File names: `obs-YYYY-MM-DD_hh-mm-ss.mp4`.
   - Recording path: `~/Documents/resolve-assist/library/footage/obs` (Simple and Advanced mode).
   - Scene collection **Content Studio**:

     | Scene | Sources |
     |---|---|
     | App screen | `Phone window`: macOS Screen Capture (window mode), fit into the canvas. No audio. |
     | Talking head | `Webcam` (MacBook Pro Camera), fills the canvas (cropped to it), plus `Mic` |
     | Voiceover | `Brand red` #E31E24 background, plus `Mic` (default input) |

3. WebSocket server: Tools → WebSocket Server Settings: enabled, port **4455**, authentication on.
   The password lives only in `~/.config/obs-websocket/password` (chmod 600, outside every repo);
   OBS keeps its own copy in `plugin_config/obs-websocket/config.json`. To change it, set the new
   password in OBS and write the same one into the file.

Other locations: `RESOLVE_ASSIST_OBS_PASSWORD_FILE`, `RESOLVE_ASSIST_OBS_PORT`, `RESOLVE_ASSIST_OBS_HOST`
(default `127.0.0.1`).

## One-time steps for you

macOS asks once per permission; OBS → Settings can't grant them. If you missed a prompt:
**System Settings → Privacy & Security** and turn OBS on under

- **Screen & System Audio Recording** (App screen). macOS then asks to quit and reopen OBS.
- **Camera** (Talking head) and **Microphone** (Talking head, Voiceover).
- **Files & Folders → Documents** for OBS. Without it the first recording waits on a prompt,
  because the recording folder is inside `~/Documents`.
- Optional: **Input Monitoring**, only for global OBS hotkeys.

Then pick the window to capture once: start iPhone Mirroring (or the iOS Simulator), and in OBS
double-click `Phone window` in the *App screen* scene → **Window** → choose it. Pick it again if the
app was restarted and the scene goes black (macOS gives the window a new id).

## Use it

CLI:

```bash
resolve-assist obs-status                      # connected? scene, recording on/off, record folder
resolve-assist obs-scenes                      # App screen, Talking head, Voiceover
resolve-assist obs-scene "Talking head"
resolve-assist obs-record --scene "App screen" # start (switches scene first)
resolve-assist obs-stop                        # stop → prints the file and indexes it in the library
resolve-assist obs-stop --no-index             # stop without touching the library index
resolve-assist import footage/obs/obs-2026-11-21_10-00-00.mp4   # into Resolve (bridge running)
```

MCP tools (Claude): `obs_status`, `obs_list_scenes`, `obs_switch_scene`, `obs_start_recording`,
`obs_stop_recording` (`refresh_library=true` by default). Example: *"Switch OBS to Talking head and
record. … Stop, and import the clip into Resolve."*

`obs_stop_recording` waits until OBS has finished the file (and, for MKV recordings with "auto remux",
until the `.mp4` is written), then re-scans the library's user folders. It doesn't regenerate assets,
so it takes well under a second. The result's `library_file` is the name for `import_assets`.

## When something fails

| Message | Fix |
|---|---|
| `OBS is not reachable at 127.0.0.1:4455` | Start OBS; check Tools → WebSocket Server Settings (enabled, port 4455) |
| `OBS rejected the password` | Copy the password from OBS (Show Connect Info) into `~/.config/obs-websocket/password` |
| `... missing or empty` | Create the password file (`chmod 600`) |
| `OBS accepted the start but is not recording` | A macOS permission prompt is probably waiting; answer it, then `obs-status` |
| `records to ..., not ...footage/obs` (warning) | OBS → Settings → Output → Recording Path → the footage folder |
| Black *App screen* | Re-pick the window (see above) or grant Screen Recording |
