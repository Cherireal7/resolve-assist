--[[
resolve-assist capability probe (READ-ONLY)

Run inside DaVinci Resolve: Workspace -> Scripts -> resolve-assist Probe
It never changes your project. It only asks Resolve what it supports and
writes a JSON report to ~/.resolve-assist/probe-report.json.

Fallback chain for the report: io library -> bmd.writefile -> console print.
]]

local PROBE_VERSION = 1
local report = { schema = PROBE_VERSION, tool = "resolve-assist probe", checks = {}, methods = {}, errors = {} }

local function safe(label, fn)
  local ok, value = pcall(fn)
  if ok then
    if value == nil then return "nil" end
    return value
  end
  report.errors[#report.errors + 1] = label .. ": " .. tostring(value)
  return "error"
end

local function typeof(v) return type(v) end

-- ---------------------------------------------------------------- Lua runtime
report.checks.lua_version = _VERSION
report.checks.jit = (jit and jit.version) or "nil"
report.checks.lib_io = typeof(io)
report.checks.lib_os = typeof(os)
report.checks.lib_debug = typeof(debug)
report.checks.fn_require = typeof(require)
report.checks.fn_loadstring = typeof(loadstring)
report.checks.lib_ffi = safe("require ffi", function() local f = require("ffi"); return type(f) end)
report.checks.os_getenv = (os and type(os.getenv)) or "nil"
report.checks.os_date = (os and os.date and os.date("!%Y-%m-%dT%H:%M:%SZ")) or "nil"

-- ---------------------------------------------------------------- bmd helpers
local bmd_keys = {}
if type(bmd) == "table" then
  for k, v in pairs(bmd) do
    if #bmd_keys < 300 then bmd_keys[#bmd_keys + 1] = tostring(k) .. ":" .. type(v) end
  end
  table.sort(bmd_keys)
end
report.checks.bmd = typeof(bmd)
report.bmd_keys = bmd_keys

-- ---------------------------------------------------------------- Resolve app
local r = resolve
if r == nil and type(Resolve) == "function" then r = safe("Resolve()", Resolve) end
if (r == nil or r == "error" or r == "nil") and type(bmd) == "table" and bmd.scriptapp then
  r = safe("bmd.scriptapp", function() return bmd.scriptapp("Resolve") end)
end
local has_resolve = type(r) == "userdata" or type(r) == "table"
report.checks.resolve_object = has_resolve and type(r) or "missing"

local function method_types(obj, names)
  local out = {}
  if obj == nil or obj == "error" or obj == "nil" then return out end
  for _, name in ipairs(names) do
    out[name] = safe("index " .. name, function() return type(obj[name]) end)
  end
  -- Control: a name that cannot exist. If this also says "function",
  -- the object answers every index and the list above proves nothing.
  out["__control_NoSuchMethod"] = safe("index control", function() return type(obj.NoSuchMethod_resolve_assist) end)
  return out
end

if has_resolve then
  report.checks.product = safe("GetProductName", function() return r:GetProductName() end)
  report.checks.version = safe("GetVersionString", function() return r:GetVersionString() end)
  report.checks.page = safe("GetCurrentPage", function() return r:GetCurrentPage() end)

  local fu = safe("Fusion()", function() return r:Fusion() end)
  if type(fu) == "userdata" or type(fu) == "table" then
    report.checks.path_userdata = safe("MapPath UserData", function() return fu:MapPath("UserData:") end)
    report.checks.path_temp = safe("MapPath Temp", function() return fu:MapPath("Temp:") end)
    report.checks.path_scripts = safe("MapPath Scripts", function() return fu:MapPath("Scripts:") end)
    report.checks.path_luts = safe("MapPath LUTs", function() return fu:MapPath("LUTs:") end)
  end

  local pm = safe("GetProjectManager", function() return r:GetProjectManager() end)
  local project = (pm ~= "error" and pm ~= "nil") and safe("GetCurrentProject", function() return pm:GetCurrentProject() end) or "nil"
  if project ~= "error" and project ~= "nil" then
    report.checks.project_open = true
    report.checks.timeline_count = safe("GetTimelineCount", function() return project:GetTimelineCount() end)
    report.methods.project = method_types(project, { "GetGallery", "GetSetting", "SetSetting", "RefreshLUTList", "ExportCurrentFrameAsStill", "GetRenderJobList" })
    report.checks.refresh_lut_list_type = report.methods.project.RefreshLUTList

    local tl = safe("GetCurrentTimeline", function() return project:GetCurrentTimeline() end)
    if tl ~= "error" and tl ~= "nil" then
      report.checks.timeline_name = safe("timeline GetName", function() return tl:GetName() end)
      report.checks.video_tracks = safe("GetTrackCount", function() return tl:GetTrackCount("video") end)
      report.checks.track1_items = safe("GetItemListInTrack", function()
        local items = tl:GetItemListInTrack("video", 1); local n = 0
        for _ in pairs(items or {}) do n = n + 1 end
        return n
      end)
      report.methods.timeline = method_types(tl, { "GetCurrentVideoItem", "GrabStill", "GrabAllStills", "Export", "GetCurrentTimecode", "SetCurrentTimecode" })

      local item = safe("GetCurrentVideoItem", function() return tl:GetCurrentVideoItem() end)
      if item ~= "error" and item ~= "nil" then
        report.checks.current_item = safe("item GetName", function() return item:GetName() end)
        report.methods.item = method_types(item, {
          "SetCDL", "SetLUT", "GetLUT", "GetNumNodes", "GetNodeGraph", "CopyGrades",
          "ApplyGradeFromDRX", "GetCurrentVersion", "AddVersion", "LoadVersionByName",
          "GetColorGroup", "ExportLUT", "SetClipColor", "GetMediaPoolItem",
        })
        report.checks.item_num_nodes = safe("item GetNumNodes", function() return item:GetNumNodes() end)
        report.checks.item_version = safe("GetCurrentVersion", function()
          local v = item:GetCurrentVersion(); return v and v.versionName or "nil"
        end)
        local graph = safe("GetNodeGraph", function() return item:GetNodeGraph() end)
        if graph ~= "error" and graph ~= "nil" then
          report.methods.graph = method_types(graph, {
            "GetNumNodes", "SetLUT", "GetLUT", "SetNodeEnabled", "GetNodeLabel",
            "ApplyGradeFromDRX", "ApplyArriCdlLut", "ResetAllGrades", "GetToolsInNode",
          })
          report.checks.graph_num_nodes = safe("graph GetNumNodes", function() return graph:GetNumNodes() end)
          report.checks.graph_lut_node1 = safe("graph GetLUT", function() return graph:GetLUT(1) end)
        end
      else
        report.checks.current_item = "none (put the playhead over a clip for a fuller report)"
      end
    end
  else
    report.checks.project_open = false
  end
end

-- ---------------------------------------------------------------- JSON
local function esc(s)
  return (s:gsub('[%c"\\]', function(c)
    local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
    return map[c] or string.format("\\u%04x", c:byte())
  end))
end

local function encode(v, depth)
  depth = depth or 0
  if depth > 8 then return '"<too deep>"' end
  local t = type(v)
  if t == "string" then return '"' .. esc(v) .. '"' end
  if t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then return "null" end
    return tostring(v)
  end
  if t == "boolean" then return tostring(v) end
  if t == "table" then
    local n = #v
    local is_array = n > 0
    if is_array then
      local parts = {}
      for i = 1, n do parts[i] = encode(v[i], depth + 1) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = tostring(k) end
    table.sort(keys)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = '"' .. esc(k) .. '":' .. encode(v[k], depth + 1) end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return '"' .. t .. '"'
end

-- ---------------------------------------------------------------- write report
local function home_dir()
  if os and os.getenv then
    local h = os.getenv("HOME") or os.getenv("USERPROFILE")
    if h and h ~= "" then return h end
  end
  local ud = report.checks.path_userdata
  if type(ud) == "string" then
    local h = ud:match("^(.-)[/\\]Library[/\\]") or ud:match("^(.-)[/\\]AppData[/\\]")
    if h then return h end
  end
  return nil
end

local home = home_dir()
local sep = package and package.config and package.config:sub(1, 1) or "/"
-- Candidate folders. The Mac App Store build is sandboxed: HOME is its container,
-- but Movies/Pictures inside the container may be links to the real user folders.
local dirs = {}
if home then
  dirs[#dirs + 1] = home .. sep .. ".resolve-assist"
  dirs[#dirs + 1] = home .. sep .. "Movies" .. sep .. "resolve-assist"
  dirs[#dirs + 1] = home .. sep .. "Pictures" .. sep .. "resolve-assist"
end
report.checks.home = home or "unknown"
report.checks.sandboxed = (home and home:find("/Library/Containers/", 1, true)) and true or false
local written = {}

local function try_io(dir)
  if not (io and io.open) then return false end
  local f = io.open(dir .. sep .. "probe-report.json", "w")
  if not f then return false end
  f:write(encode(report)); f:close()
  return true
end

local function try_bmd(dir)
  if not (type(bmd) == "table" and bmd.writefile) then return false end
  return pcall(function()
    if bmd.createdir then bmd.createdir(dir) end
    bmd.writefile(dir .. sep .. "probe-report.lua", { json = encode(report) })
  end)
end

for _, dir in ipairs(dirs) do
  if try_io(dir) then written[#written + 1] = dir .. " (io)"
  elseif try_bmd(dir) then written[#written + 1] = dir .. " (bmd.writefile)" end
end
report.checks.report_written_to = written
local json_text = encode(report)
written = (#written > 0) and table.concat(written, ", ") or nil

print("")
print("==== resolve-assist probe ====")
print("Resolve: " .. tostring(report.checks.product) .. " " .. tostring(report.checks.version))
print("Report written: " .. tostring(written or "NO - copy the JSON below and send it"))
print("---- BEGIN PROBE JSON ----")
print(json_text)
print("---- END PROBE JSON ----")
