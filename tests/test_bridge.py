"""End-to-end: real bridge.lua (in lupa, on a thread) <-> real Python client, through real files."""

import json
import os
import threading
import time
import unittest
from pathlib import Path

from resolve_assist import api
from resolve_assist.bridge import Bridge, BridgeError, BridgeOffline, loader_code
from resolve_assist.imaging.png import encode_png

from helpers import TempEnv, scene

try:
    import lupa.luajit21 as lupa
except ImportError:
    try:
        import lupa.lua51 as lupa
    except ImportError:
        try:
            import lupa
        except ImportError:
            lupa = None

FAKE = r"""
local _io = io
local function file_obj(fh)
  return {
    ReadLine = function(self) local l = fh:read("*l"); if l then return l .. "\n" end; return nil end,
    WriteLine = function(self, s) fh:write(s, "\n"); return #s + 1 end,
    Flush = function(self) fh:flush(); return true end,
    Close = function(self) fh:close() end,
    GetFileSize = function(self) local cur = fh:seek(); local size = fh:seek("end"); fh:seek("set", cur); return size end,
  }
end
fu = {
  OpenFile = function(self, path, mode)
    local fh = _io.open(path, mode == 1 and "r" or "w")
    if not fh then return nil end
    return file_obj(fh)
  end,
  MapPath = function(self, p) if p == "LUTs:" then return FUSION_LUTS .. "/" end; return SCRIPTS_DIR .. "/" end,
}
bmd = {
  wait = function(s) PY_SLEEP(0.01) end,
  createuuid = function() return "session-test" end,
  fileexists = function(p) local f = _io.open(p, "r"); if f then f:close(); return true end; return false end,
}

local function make_comp(owner)
  local tools = {}
  local comp = {}
  local function tool(name, id)
    local t = { Name = name, id = id, inputs = {} }
    t.SetAttrs = function(self, a)
      if a.TOOLS_Name then tools[self.Name] = nil; self.Name = a.TOOLS_Name; tools[self.Name] = self end
    end
    t.SetInput = function(self, k, v) self.inputs[k] = v; if k == "StyledText" then RECORD("SetInput", owner, k, v, 0) end end
    t.ConnectInput = function(self, k, src)
      self.inputs[k] = src
      if src == nil then return true end  -- disconnect
      local from = (src.tool and src.tool.Name) or src.Name or "?"
      RECORD("Connect", owner, self.Name .. "." .. k, from, 0)
    end
    t.Output = { tool = t }
    t.FindMainInput = function(self, i) return self.Input end
    t.Input = { GetConnectedOutput = function() local i = t.inputs.Input; return i and (i.Output or i) end }
    tools[name] = t
    return t
  end
  tool("MediaIn1", "MediaIn")
  local mo = tool("MediaOut1", "MediaOut")
  mo.inputs.Input = tools.MediaIn1
  comp.FindTool = function(self, n) return tools[n] end
  comp.AddTool = function(self, id) return tool(id .. "1", id) end
  comp.Lock = function() end
  comp.Unlock = function() end
  comp.GetAttrs = function(self, key)
    local a = { COMPN_GlobalStart = 216000, COMPN_GlobalEnd = 216372, COMPN_RenderStart = 0, COMPN_RenderEnd = 372 }
    if key then return a[key] end
    return a
  end
  comp.GetToolList = function() local out = {}; for _, t in pairs(tools) do out[#out + 1] = t end; return out end
  comp.BezierSpline = function() return {} end
  return comp
end

local function clip(name, s, e)
  local c = { name = name, s = s, e = e, version = "Version 1", versions = { ["Version 1"] = true }, lut = "" }
  c.GetName = function(self) return self.name end
  c.GetStart = function(self) return self.s end
  c.GetEnd = function(self) return self.e end
  c.GetNumNodes = function(self) return 1 end
  c.GetCurrentVersion = function(self) return { versionName = self.version, versionType = 0 } end
  c.AddVersion = function(self, n) self.versions[n] = true; return true end
  c.LoadVersionByName = function(self, n) if self.versions[n] then self.version = n; return true end; return false end
  c.SetCDL = function(self, t) RECORD("SetCDL", self.name, self.version, t.Slope, t.NodeIndex); return true end
  local graph = {}
  graph.SetLUT = function(g, node, path)
    RECORD("SetLUT", c.name, c.version, path, node)
    if ALLOW_LUT(path) then c.lut = path; return true end
    return false
  end
  graph.GetLUT = function(g, node) return c.lut end
  graph.ApplyGradeFromDRX = function(g, path, mode) RECORD("ApplyDRX", c.name, c.version, path, mode); return true end
  c.GetNodeGraph = function(self) return graph end
  c.SetLUT = graph.SetLUT
  c.GetLUT = graph.GetLUT
  c.Stabilize = function(self) RECORD("Stabilize", self.name, self.version, "", 0); return true end
  c.comps = {}
  c.GetFusionCompCount = function(self) return #self.comps end
  c.GetFusionCompByIndex = function(self, i) return self.comps[i] end
  c.AddFusionComp = function(self) local k = make_comp(self.name); self.comps[#self.comps + 1] = k; return k end
  return c
end
local clips = { clip("A.mp4", 86400, 86500), clip("B.mp4", 86500, 86700) }
local tc = "01:00:00:00"
local function make_timeline(name)
  local t = { name = name, tracks = { video = 1, audio = 1, subtitle = 0 }, locked = {}, settings = {} }
  t.SetSetting = function(self, k, v) self.settings[k] = v; RECORD("SetSetting", self.name, k, v, 0); return true end
  t.GetSetting = function(self, k) if k == "timelineFrameRate" then return "25" end; return self.settings[k] end
  t.GetName = function(self) return self.name end
  t.GetTrackCount = function(self, kind) return self.tracks[kind or "video"] end
  t.AddTrack = function(self, kind) self.tracks[kind] = self.tracks[kind] + 1; return true end
  t.SetTrackLock = function(self, kind, i, v) self.locked[i] = v; return true end
  t.GetItemListInTrack = function(self, kind, i) if i == 1 then return clips end; return {} end
  t.GetCurrentVideoItem = function() return clips[1] end
  t.SetCurrentTimecode = function(self, v) tc = v; return true end
  t.GetCurrentTimecode = function() return tc end
  t.GetStartFrame = function() return 86400 end
  t.AddMarker = function(self, f, color, label) RECORD("Marker", self.name, tostring(f), label, 0); return true end
  t.GetEndFrame = function() return 86700 end
  t.DuplicateTimeline = function(self, n) return make_timeline(n) end
  t.InsertFusionTitleIntoTimeline = function(self, kind)
    local locked = {}
    for k, v in pairs(self.locked) do if v then locked[#locked + 1] = k end end
    RECORD("InsertTitle", self.name, tc, kind, #locked)
    local tool = { SetInput = function(_, key, value) RECORD("SetInput", self.name, key, value, 0) end }
    local comp = { FindToolByID = function(_, id) if id == "TextPlus" then return tool end end }
    return { GetFusionCompByIndex = function() return comp end, GetStart = function() return 86400 end,
             GetEnd = function() return 86525 end }
  end
  return t
end
local timelines = { make_timeline("Timeline 1") }
local current = timelines[1]
local function folder(name)
  local f = { name = name, subs = {}, clips = {} }
  f.GetName = function(self) return self.name end
  f.GetSubFolderList = function(self) return self.subs end
  f.GetClipList = function(self) return self.clips end
  return f
end
local function pool_clip(path, fps, frames)
  return { path = path, GetName = function() return path:match("[^/]+$") end,
           GetClipProperty = function(_, k)
             if k == "File Path" then return path elseif k == "FPS" then return fps elseif k == "Frames" then return frames end
           end }
end
local root_folder = folder("Master")
root_folder.clips = { pool_clip("/Users/x/Downloads/a.mp4", "25", "500") }
local current_folder = root_folder
local media_pool = {
  GetRootFolder = function() return root_folder end,
  AddSubFolder = function(self, parent, name) local f = folder(name); table.insert(parent.subs, f); return f end,
  GetCurrentFolder = function() return current_folder end,
  SetCurrentFolder = function(self, f) current_folder = f; return true end,
  ImportMedia = function(self, paths)
    local out = {}
    for _, p in ipairs(paths) do
      RECORD("ImportMedia", current_folder.name, "", p, #paths)
      local c = pool_clip(p, "25", "200")
      c.is_srt = p:match("%.srt$") ~= nil
      out[#out + 1] = c
    end
    return out
  end,
  DeleteTimelines = function(self, list)
    for _, t in ipairs(list) do
      for i, x in ipairs(timelines) do if x == t then table.remove(timelines, i); break end end
      RECORD("DeleteTimeline", t.name, "", "", 0)
    end
    return true
  end,
  CreateEmptyTimeline = function(self, name)
    local t = make_timeline(name); timelines[#timelines + 1] = t; current = t
    RECORD("CreateTimeline", name, "", "", 0)
    return t
  end,
  AppendToTimeline = function(self, infos)
    local i = infos[1]
    if i.mediaPoolItem and i.mediaPoolItem.is_srt then current.tracks.subtitle = 1; return { {} } end
    if #infos > 1 or (i.mediaType == 1) then
      local out = {}
      for _, x in ipairs(infos) do
        RECORD("AppendSeg", x.mediaPoolItem.path or "?", tostring(x.startFrame), tostring(x.endFrame), x.mediaType)
        out[#out + 1] = {}
      end
      return out
    end
    if i.trackIndex then
      RECORD("AppendAudio", (i.mediaPoolItem.path or "?"):match("[^/]+$"), tostring(i.trackIndex), tostring(i.recordFrame), i.mediaType)
    end
    RECORD("AppendToTimeline", current.name, tostring(i.trackIndex), tostring(i.endFrame), i.mediaType)
    return { {} }
  end,
}
local project = {
  GetName = function() return "Test Project" end,
  GetCurrentTimeline = function() return current end,
  GetTimelineCount = function() return #timelines end,
  GetTimelineByIndex = function(self, i) return timelines[i] end,
  SetCurrentTimeline = function(self, t)
    local known = false
    for _, x in ipairs(timelines) do if x == t then known = true end end
    if not known then timelines[#timelines + 1] = t end
    current = t; return true
  end,
  GetMediaPool = function() return media_pool end,
  GetSetting = function() return nil end,
  RefreshLUTList = function() return true end,
  ExportCurrentFrameAsStill = function(self, path)
    local f = _io.open(path, "wb"); f:write(FAKE_PNG); f:close(); return true
  end,
}
resolve = {
  GetVersionString = function() return "21.2.0.6" end,
  GetCurrentPage = function() return "color" end,
  GetProjectManager = function() return { GetCurrentProject = function() return project end } end,
}
print = function() end
io = nil      -- like Resolve Free 21.2: no io library
require = nil
"""


@unittest.skipIf(lupa is None, "pip install lupa to run the bridge test")
class BridgeEndToEnd(unittest.TestCase):
    def setUp(self):
        self.env = TempEnv().__enter__()
        res = api.bridge_install(copy_to_clipboard=False)
        self.root = Path(res["bridge"]).parent
        self.scripts = self.env.root / "Scripts"
        for sub in ("Utility", "Color"):
            (self.scripts / sub).mkdir(parents=True)
        w, h, px = scene(cast=(1.1, 1.0, 0.9))
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.PY_SLEEP = time.sleep
        # Recorded on the Python side: reading Lua globals would block while the bridge loop runs.
        self.recorded = []
        g.RECORD = lambda op, clip, version, value, node: self.recorded.append(
            {"op": op, "clip": clip, "version": version, "value": value, "node": node})
        g.SCRIPTS_DIR = str(self.scripts)
        self.fusion_luts = self.env.root / "FusionLUTs"
        self.fusion_luts.mkdir()
        g.FUSION_LUTS = str(self.fusion_luts)
        # Like real Resolve: LUTs load only from its own LUT folder (decided in Python: no Lua lock).
        self.lut_allowed_prefix = str(self.fusion_luts)
        g.ALLOW_LUT = lambda path: str(path).startswith(self.lut_allowed_prefix)
        g.FAKE_PNG = encode_png(w, h, px)
        self.lua.execute(FAKE)
        self.errors = []
        src = (self.root / "bridge.lua").read_text()
        g.BRIDGE_MAX_LOOPS = 3000  # safety stop (~30 s)

        def run():
            try:
                self.lua.execute(src)
            except Exception as exc:  # surfaced in tearDown
                self.errors.append(exc)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        deadline = time.time() + 5
        while not Bridge().status().get("running") and time.time() < deadline:
            time.sleep(0.02)

    def tearDown(self):
        try:
            Bridge().call("stop", timeout=5)
        except BridgeError:
            pass
        self.thread.join(timeout=5)
        self.env.__exit__(None, None, None)
        self.assertEqual(self.errors, [])

    def calls(self):
        return list(self.recorded)

    def test_status_clips_and_menu(self):
        st = api.bridge_status()
        self.assertTrue(st["running"])
        self.assertEqual(st["resolve"]["timeline"], "Timeline 1")
        self.assertEqual(sorted(st["menu"]), ["Color", "Utility"])
        self.assertTrue((self.scripts / "Utility" / "resolve-assist Bridge.lua").read_text().startswith("-- resolve-assist"))
        clips = api.clips()
        self.assertEqual([c["target"] for c in clips["clips"]], ["1:1", "1:2"])

    def test_grab_and_analyze_with_goto(self):
        res = api.analyze_clip("1:2")
        self.assertTrue(Path(res["frame_path"]).is_file())
        self.assertGreater(res["analysis"]["cast"]["red"], 0.03)

    def test_dry_run_changes_nothing_then_apply_and_undo(self):
        plan = api.apply_grade("current", slope="0.95 1 1.08", saturation=0.9)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(self.calls(), [])
        done = api.apply_grade("current", slope="0.95 1 1.08", saturation=0.9, confirm=True)
        self.assertTrue(done["applied"])
        self.assertIn("after", done)
        call = self.calls()[0]
        self.assertEqual((call["op"], call["value"], call["version"]), ("SetCDL", "0.9500 1.0000 1.0800", "resolve-assist"))
        self.assertEqual(done["resolve"]["previous_version"], "Version 1")
        undo = api.undo_grade("current")
        self.assertEqual(undo["restored_version"], "Version 1")
        self.assertEqual(undo["resolve"]["clip"]["version"], "Version 1")

    def test_look_lut_is_copied_into_resolves_lut_folder(self):
        done = api.apply_grade("1:2", slope="0.95 1 1.05", look="warm-film", strength=0.5, confirm=True, verify=False)
        self.assertEqual(done["plan"]["method"], "cdl+lut")
        ops = [c["op"] for c in self.calls()]
        self.assertEqual(ops[0], "SetCDL")                       # correction first
        self.assertIn("SetLUT", ops)
        final = [c for c in self.calls() if c["op"] == "SetLUT"][-1]["value"]
        self.assertTrue(final.startswith(str(self.fusion_luts)))  # copied by Lua into Resolve's folder
        self.assertTrue(Path(final).is_file())
        self.assertEqual(Path(final).read_text().splitlines()[2], "LUT_3D_SIZE 33")

    def test_look_falls_back_to_cdl_when_resolve_refuses_luts(self):
        self.lut_allowed_prefix = "/nowhere"
        done = api.apply_grade("current", slope="0.95 1 1.05", look="clean-commercial", strength=0.6,
                               confirm=True, verify=False)
        self.assertEqual(done["plan"]["method"], "cdl-approximation")
        last = self.calls()[-1]
        self.assertEqual(last["op"], "SetCDL")
        self.assertNotEqual(last["value"], "0.9500 1.0000 1.0500")  # look folded into the correction

    def test_music_and_title_only_on_a_timeline_copy(self):
        media = self.env.root / "out" / "media"
        (media / "song.wav").write_bytes(b"RIFF")
        with self.assertRaises(BridgeError):
            Bridge().call("add_title", text="x")        # refuses the original timeline
        res = api.add_music("song.wav")
        self.assertEqual(res["timeline"]["timeline"], "Timeline 1 (resolve-assist)")
        self.assertTrue(res["timeline"]["created"])
        imported = [c for c in self.calls() if c["op"] == "ImportMedia"][0]
        self.assertEqual(imported["value"], str((media / "song.wav").resolve()))
        placed = [c for c in self.calls() if c["op"] == "AppendToTimeline"][0]
        self.assertEqual(placed["clip"], "Timeline 1 (resolve-assist)")
        self.assertEqual((placed["version"], placed["value"], placed["node"]), ("2", "199", 2))  # audio track 2
        t = api.add_title("Nail Art | Session", at_seconds=1.0)
        self.assertFalse(t["timeline"]["created"])                    # reuses the copy
        self.assertTrue(t["title"]["timed"])
        self.assertNotIn("InsertTitle", [c["op"] for c in self.calls()])  # never an insert edit
        text = [c for c in self.calls() if c["op"] == "SetInput"][0]
        self.assertEqual((text["version"], text["value"]), ("StyledText", "Nail Art \n Session"))
        wires = {c["version"]: c["value"] for c in self.calls() if c["op"] == "Connect"}
        self.assertEqual(wires, {"RA_TitleMerge.Background": "MediaIn1", "RA_TitleMerge.Foreground": "RA_Title",
                                 "MediaOut1.Input": "RA_TitleMerge"})
        self.assertEqual(t["title"]["comp"]["attrs"]["RenderStart"], 0)
        self.assertIn("RA_Title", t["title"]["comp"]["tools"])
        api.add_title("Changed", at_seconds=0.5)                      # second call edits, no new nodes
        self.assertEqual(len([c for c in self.calls() if c["op"] == "Connect"]), 3)
        reset = api.reset_copy()
        self.assertEqual(reset, {"deleted": True, "original": "Timeline 1"})
        self.assertEqual([c["clip"] for c in self.calls() if c["op"] == "DeleteTimeline"], ["Timeline 1 (resolve-assist)"])
        self.assertFalse(api.reset_copy()["deleted"])                 # original is never deleted
        with self.assertRaises(ValueError):
            api.add_music("../../secret.wav")
        with self.assertRaises(ValueError):
            api.add_title("two\nlines")

    def test_import_assets_and_powergrade_from_library_only(self):
        lib = self.env.root / "out" / "library"
        (lib / "sfx").mkdir(parents=True)
        (lib / "powergrades").mkdir()
        (lib / "sfx" / "whoosh-medium.wav").write_bytes(b"RIFF")
        (lib / "powergrades" / "film.drx").write_text("<drx/>")
        (lib / "manifest.json").write_text('{"items": [{"id": "whoosh-medium", "category": "sfx", '
                                           '"file": "sfx/whoosh-medium.wav", "tags": ["whoosh"], "usage": "x", "license": "x"}]}')
        res = api.import_assets(["whoosh-medium"])
        self.assertEqual(res["imported"], ["whoosh-medium.wav"])
        imp = [c for c in self.calls() if c["op"] == "ImportMedia"][-1]
        self.assertEqual(imp["clip"], "resolve-assist library")             # into the bin
        self.assertEqual(imp["value"], str((lib / "sfx" / "whoosh-medium.wav").resolve()))
        api.import_assets(["sfx/whoosh-medium.wav"])                        # reuses the bin
        g = api.apply_powergrade("film.drx", "1:2")
        self.assertTrue(g["ok"])
        drx = [c for c in self.calls() if c["op"] == "ApplyDRX"][-1]
        self.assertEqual((drx["version"], drx["value"]), ("resolve-assist", str((lib / "powergrades" / "film.drx").resolve())))
        with self.assertRaises(ValueError):
            api.import_assets(["../../.ssh/id_rsa"])
        with self.assertRaises(BridgeError):
            Bridge().call("import_media", files="../secret.wav")            # Lua-side check too
        with self.assertRaises(BridgeError):
            Bridge().call("apply_drx", file="sfx/whoosh-medium.wav")        # only powergrades/*.drx

    def test_vertical_format_copy(self):
        res = api.make_format("9x16")
        self.assertEqual(res["timeline"], "Timeline 1 9x16 (resolve-assist)")
        self.assertTrue(res["created"])
        self.assertEqual((res["now"]["width"], res["now"]["height"]), ("1080", "1920"))
        self.assertEqual(res["now"]["fit"], "scaleToFit")
        again = api.make_format("9x16")                       # from the copy: reuses, no copy-of-copy
        self.assertFalse(again["created"])
        self.assertEqual(again["timeline"], "Timeline 1 9x16 (resolve-assist)")
        with self.assertRaises(ValueError):
            api.make_format("21x9")
        self.assertEqual(api.reset_copy()["original"], "Timeline 1")

    def test_import_subtitles_only_on_copy(self):
        caps = self.env.root / "out" / "captions"
        caps.mkdir(parents=True, exist_ok=True)
        (caps / "t.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        with self.assertRaises(BridgeError):
            Bridge().call("import_subtitles", file="t.srt")   # original timeline refused
        Bridge().call("duplicate_timeline")
        res = Bridge().call("import_subtitles", file="t.srt")
        self.assertTrue(res["placed"])
        self.assertTrue(res["added_track"])
        with self.assertRaises(BridgeError):
            Bridge().call("import_subtitles", file="../x.srt")

    def test_build_edit_new_timeline_with_music_sfx_markers(self):
        lib = self.env.root / "out" / "library"
        (lib / "sfx").mkdir(parents=True)
        (lib / "music").mkdir()
        (lib / "sfx" / "whoosh-medium.wav").write_bytes(b"RIFF")
        (lib / "music" / "calm-lofi-30s.wav").write_bytes(b"RIFF")
        (lib / "manifest.json").write_text('{"items": [{"id": "whoosh-medium", "category": "sfx", "file": "sfx/whoosh-medium.wav",'
                                           ' "tags": [], "usage": "", "license": ""}, {"id": "calm-lofi-30s", "category": "music",'
                                           ' "file": "music/calm-lofi-30s.wav", "tags": [], "usage": "", "license": ""}]}')
        segs = [{"source": "/Users/x/Downloads/a.mp4", "source_in": 1.0, "source_out": 2.0},
                {"source": "/Users/x/Downloads/a.mp4", "source_in": 5.0, "source_out": 5.5}]
        res = api.build_edit(segs, title="Nails", music="calm-lofi-30s", sfx_on_cuts="whoosh-medium")
        self.assertEqual(res["timeline"], "Nails (resolve-assist)")
        seg_calls = [(c["version"], c["value"]) for c in self.calls() if c["op"] == "AppendSeg"]
        self.assertEqual(seg_calls, [("25", "49"), ("125", "137")])   # 25 fps; out 5.5 s = frame 137.5 → last frame 137
        audio = [(c["clip"], c["version"]) for c in self.calls() if c["op"] == "AppendAudio"]
        self.assertIn(("calm-lofi-30s.wav", "1"), audio)                # music on A1
        self.assertIn(("whoosh-medium.wav", "2"), audio)                # whoosh on A2
        sfx_rec = [c["value"] for c in self.calls() if c["op"] == "AppendAudio" and c["clip"] == "whoosh-medium.wav"][0]
        self.assertEqual(sfx_rec, str(86400 + round(0.6 * 25)))         # 0.4 s before the cut at 1.0 s
        self.assertEqual([c["version"] for c in self.calls() if c["op"] == "Marker"], ["25"])
        again = api.build_edit(segs[:1], title="Nails")
        self.assertEqual(again["timeline"], "Nails 2 (resolve-assist)")  # never overwrites
        with self.assertRaises(BridgeError):                               # not in pool, not allowed
            api.build_edit([{"source": "/etc/hosts.mp4", "source_in": 0, "source_out": 1}])

    def test_stabilize(self):
        res = api.stabilize("current")
        self.assertTrue(res["ok"])
        self.assertEqual(self.calls()[-1]["op"], "Stabilize")
        self.assertEqual(self.calls()[-1]["version"], "resolve-assist")

    def test_security_rejections(self):
        b = Bridge()
        with self.assertRaises(BridgeError):
            b.call("run_lua")                                   # client-side allowlist
        with self.assertRaises(BridgeError):
            b.call("apply_lut", lut="../../etc/evil.cube")      # Lua-side name check
        with self.assertRaises(BridgeError):
            b.call("apply_cdl", slope="1 1 1; os.exit()", offset="0 0 0", power="1 1 1")
        with self.assertRaises(BridgeError):
            b.call("clip_info", target="current\nop\tstop")     # no line injection
        # A forged raw request with a wrong session id is refused by Lua.
        (self.root / "request.txt").write_text(f"seq\t{int(time.time()*1000)+5000}\nsession\tforged\nts\t{int(time.time())}\nop\tstop\n")
        time.sleep(0.4)
        resp = json.loads((self.root / "response.txt").read_text().splitlines()[0])
        self.assertFalse(resp["ok"])
        self.assertIn("session", resp["error"])
        self.assertTrue(Bridge().status()["running"])
        self.assertEqual(self.calls(), [])


class BridgeOfflineTests(unittest.TestCase):
    def test_offline_and_loader(self):
        with TempEnv():
            self.assertFalse(api.bridge_status()["running"])
            with self.assertRaises(BridgeOffline):
                api.clips()
            self.assertTrue(api.apply_grade(slope=1.1)["dry_run"])  # dry run works offline
            code = loader_code(Path('/x/"q".lua'))
            self.assertIn('\\"q\\"', code)
            with self.assertRaises(ValueError):
                loader_code(Path("/x/a\nb.lua"))


if __name__ == "__main__":
    unittest.main()
