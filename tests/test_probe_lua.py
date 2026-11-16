"""Run the real probe.lua in a Lua runtime (lupa) against a fake Resolve."""

import json
import tempfile
import unittest
from importlib import resources
from pathlib import Path

try:  # prefer LuaJIT 2.1, the runtime Resolve embeds
    import lupa.luajit21 as lupa
except ImportError:
    try:  # then Lua 5.1, the same language version
        import lupa.lua51 as lupa
    except ImportError:
        try:
            import lupa
        except ImportError:  # optional dev dependency
            lupa = None

PROBE = resources.files("resolve_assist").joinpath("lua/probe.lua").read_text(encoding="utf-8")

FAKE_RESOLVE = r"""
local function obj(t) return t end
local graph = obj{ GetNumNodes = function(self) return 2 end, GetLUT = function(self, i) return "" end,
                   SetLUT = function() error("probe must not call SetLUT") end }
local item = obj{ GetName = function(self) return "clip1" end, GetNumNodes = function(self) return 2 end,
                  GetNodeGraph = function(self) return graph end,
                  GetCurrentVersion = function(self) return { versionName = "Version 1" } end,
                  SetCDL = function() error("probe must not call SetCDL") end }
local tl = obj{ GetName = function(self) return "Timeline 1" end, GetTrackCount = function(self) return 1 end,
                GetItemListInTrack = function(self) return { item } end,
                GetCurrentVideoItem = function(self) return item end }
local project = obj{ GetTimelineCount = function(self) return 1 end, GetCurrentTimeline = function(self) return tl end }
local pm = obj{ GetCurrentProject = function(self) return project end }
local fu = obj{ MapPath = function(self, p) return HOME_FOR_TEST .. "/Library/Application Support/X/" .. p end }
resolve = obj{ GetProductName = function(self) return "DaVinci Resolve" end,
               GetVersionString = function(self) return "21.2.0.6" end,
               GetCurrentPage = function(self) return "edit" end,
               Fusion = function(self) return fu end,
               GetProjectManager = function(self) return pm end }
"""


@unittest.skipIf(lupa is None, "pip install lupa to run the Lua probe test")
class ProbeLuaTests(unittest.TestCase):
    def run_probe(self, home: Path, with_io: bool = True):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        lua.globals().HOME_FOR_TEST = str(home)
        lua.execute(f'os.getenv = function(k) if k == "HOME" then return "{home}" end end')
        if not with_io:
            lua.execute("io = nil")
        lua.execute("print = function() end")
        lua.execute(FAKE_RESOLVE)
        lua.execute(PROBE)

    def test_sandboxed_home_writes_to_movies(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data"
            (home / "Movies/resolve-assist").mkdir(parents=True)  # .resolve-assist missing, like the sandbox
            self.run_probe(home)
            report = json.loads((home / "Movies/resolve-assist/probe-report.json").read_text())
            c = report["checks"]
            self.assertEqual(c["version"], "21.2.0.6")
            self.assertTrue(c["sandboxed"])
            self.assertEqual(c["current_item"], "clip1")
            self.assertEqual(c["graph_num_nodes"], 2)
            self.assertEqual(report["methods"]["item"]["SetCDL"], "function")
            self.assertEqual(report["methods"]["item"]["__control_NoSuchMethod"], "nil")
            # ffi exists only in LuaJIT; plain Lua test runtimes report it missing
            self.assertEqual([e for e in report["errors"] if not e.startswith("require ffi")], [])

    def test_no_io_falls_back_to_console_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_probe(Path(tmp), with_io=False)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
