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
  MapPath = function(self, p) return SCRIPTS_DIR .. "/" end,
}
bmd = {
  wait = function(s) PY_SLEEP(0.01) end,
  createuuid = function() return "session-test" end,
  fileexists = function(p) local f = _io.open(p, "r"); if f then f:close(); return true end; return false end,
}

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
  graph.SetLUT = function(g, node, path) RECORD("SetLUT", c.name, c.version, path, node); c.lut = path; return true end
  graph.GetLUT = function(g, node) return c.lut end
  c.GetNodeGraph = function(self) return graph end
  c.SetLUT = graph.SetLUT
  c.GetLUT = graph.GetLUT
  return c
end
local clips = { clip("A.mp4", 86400, 86500), clip("B.mp4", 86500, 86700) }
local tc = "01:00:00:00"
local tl = {
  GetName = function() return "Timeline 1" end,
  GetTrackCount = function() return 1 end,
  GetItemListInTrack = function(self, kind, t) return clips end,
  GetCurrentVideoItem = function() return clips[1] end,
  GetSetting = function(self, k) if k == "timelineFrameRate" then return "25" end end,
  SetCurrentTimecode = function(self, t) tc = t; return true end,
  GetCurrentTimecode = function() return tc end,
}
local project = {
  GetName = function() return "Test Project" end,
  GetCurrentTimeline = function() return tl end,
  GetSetting = function() return nil end,
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

    def test_look_goes_through_a_lut_in_the_allowlisted_folder(self):
        done = api.apply_grade("1:2", look="warm-film", strength=0.5, confirm=True, verify=False)
        call = self.calls()[0]
        self.assertEqual(call["op"], "SetLUT")
        self.assertTrue(Path(call["value"]).is_file())
        self.assertEqual(Path(call["value"]).parent, (self.env.root / "out" / "LUTs"))
        self.assertTrue(done["applied"])

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
