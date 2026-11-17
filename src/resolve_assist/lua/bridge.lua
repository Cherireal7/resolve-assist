--[[
resolve-assist bridge (Phase 2), protocol 2

Runs inside DaVinci Resolve (Free or Studio). Started by the loader that
`resolve-assist bridge-install` puts on your clipboard, or from the Scripts menu
after the first run. It talks to the resolve-assist server through files in a
shared folder (works in the sandboxed Mac App Store build: uses fu:OpenFile,
no io library needed).

Security:
- Only the operations in OPS below can run. Request data is NEVER executed.
- Requests must carry this run's session id and be fresh (MAX_AGE seconds).
- LUTs are only loaded from the resolve-assist LUT folder.
- Before the first change on a clip it switches to a separate grade version
  named "resolve-assist", so your own grade is untouched and undo is one click.
]]

local BRIDGE_DIR = BRIDGE_DIR_OVERRIDE or {{BRIDGE_DIR}}
local LUT_DIR = LUT_DIR_OVERRIDE or {{LUT_DIR}}
local PROTOCOL = 2
local POLL_SECONDS = BRIDGE_POLL_SECONDS or 0.1
local MAX_LOOPS = BRIDGE_MAX_LOOPS          -- tests only; nil = run until stopped
local MAX_AGE = 60                          -- seconds a request stays valid
local AI_VERSION = "resolve-assist"
local MAX_REQUEST_BYTES = 16384

local app = fusion or fu
local r = resolve or (bmd and bmd.scriptapp and bmd.scriptapp("Resolve"))
assert(app and app.OpenFile, "resolve-assist: this Resolve build has no fu:OpenFile")
assert(r, "resolve-assist: no Resolve object (open a project first)")

-- ------------------------------------------------------------------ JSON out
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
    if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
    return tostring(v)
  end
  if t == "boolean" then return tostring(v) end
  if t == "nil" then return "null" end
  if t == "table" then
    if #v > 0 then
      local parts = {}
      for i = 1, #v do parts[i] = encode(v[i], depth + 1) end
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

-- ------------------------------------------------------------------ files
local function read_lines(path, limit)
  local f = app:OpenFile(path, 1)
  if not f then return nil end
  local ok, size = pcall(function() return f:GetFileSize() end)
  if ok and size and size > limit then f:Close(); return nil end
  local out = {}
  for _ = 1, 500 do
    local line = f:ReadLine()
    if line == nil then break end
    out[#out + 1] = (line:gsub("[\r\n]+$", ""))
  end
  f:Close()
  return out
end

local function write_line(path, text)
  local f = app:OpenFile(path, 2)
  if not f then return false end
  f:WriteLine(text)
  f:Flush()
  f:Close()
  return true
end

-- ------------------------------------------------------------------ Resolve helpers
local running = true
local session = (bmd and bmd.createuuid and bmd.createuuid()) or tostring(os.time())

local function project()
  local p = r:GetProjectManager():GetCurrentProject()
  assert(p, "no project is open")
  return p
end

local function timeline()
  local t = project():GetCurrentTimeline()
  assert(t, "no timeline is open")
  return t
end

local function fps_of(tl)
  return tonumber(tl:GetSetting("timelineFrameRate")) or tonumber(project():GetSetting("timelineFrameRate")) or 24
end

local function frames_to_tc(frames, fps)
  local n = math.floor(fps + 0.5)
  local s = math.floor(frames / n)
  return string.format("%02d:%02d:%02d:%02d", math.floor(s / 3600), math.floor(s / 60) % 60, s % 60, frames % n)
end

local function info(it, target)
  if not it then return nil end
  local v = it:GetCurrentVersion() or {}
  return {
    name = it:GetName(), start = it:GetStart(), ["end"] = it:GetEnd(),
    nodes = it:GetNumNodes(), version = v.versionName, target = target,
  }
end

local function item_for(target)
  local tl = timeline()
  if target == nil or target == "" or target == "current" then
    local it = tl:GetCurrentVideoItem()
    assert(it, "no clip under the playhead")
    return it, tl
  end
  local track, index = target:match("^(%d+):(%d+)$")
  assert(track, "target must be 'current' or 'track:index' like '1:2'")
  local items = tl:GetItemListInTrack("video", tonumber(track)) or {}
  local it = items[tonumber(index)]
  assert(it, "no clip at " .. target)
  return it, tl
end

local function ensure_ai_version(it)
  local prev = (it:GetCurrentVersion() or {}).versionName
  if prev == AI_VERSION then return prev end
  local loaded = it:LoadVersionByName(AI_VERSION, 0)
  if not loaded then
    assert(it:AddVersion(AI_VERSION, 0), "could not create the resolve-assist grade version")
    loaded = it:LoadVersionByName(AI_VERSION, 0)
  end
  assert(loaded, "could not switch to the resolve-assist grade version")
  return prev
end

local function triple(s, name)
  assert(type(s) == "string" and s:match("^%-?[%d%.]+ %-?[%d%.]+ %-?[%d%.]+$"), name .. " must be three numbers")
  for v in s:gmatch("%S+") do assert(tonumber(v), name .. " contains a non-number") end
  return s
end

local function node_of(req)
  local n = tonumber(req.node or "1")
  assert(n and n >= 1 and n <= 64 and n == math.floor(n), "node must be a whole number 1..64")
  return n
end

-- ------------------------------------------------------------------ allowlisted operations
local OPS = {}

function OPS.status()
  local p = r:GetProjectManager():GetCurrentProject()
  local tl = p and p:GetCurrentTimeline()
  return {
    version = r:GetVersionString(), page = r:GetCurrentPage(),
    project = p and p:GetName() or nil, timeline = tl and tl:GetName() or nil,
    current = tl and info(tl:GetCurrentVideoItem(), "current") or nil,
  }
end

function OPS.list_clips()
  local tl = timeline()
  local out = {}
  for t = 1, tl:GetTrackCount("video") do
    for i, it in ipairs(tl:GetItemListInTrack("video", t) or {}) do
      out[#out + 1] = info(it, t .. ":" .. i)
    end
  end
  return { timeline = tl:GetName(), fps = fps_of(tl), clips = out }
end

function OPS.clip_info(req)
  local it = item_for(req.target)
  return info(it, req.target)
end

function OPS.goto_clip(req)
  local it, tl = item_for(req.target)
  local mid = math.floor((it:GetStart() + it:GetEnd()) / 2)
  local tc = frames_to_tc(mid, fps_of(tl))
  local ok = tl:SetCurrentTimecode(tc)
  return { ok = ok and true or false, timecode = tc, now = tl:GetCurrentTimecode(), clip = info(it, req.target) }
end

function OPS.grab_frame(req)
  if req.target and req.target ~= "" and req.target ~= "current" then OPS.goto_clip(req) end
  local path = BRIDGE_DIR .. "/frames/frame-" .. req.seq .. ".png"
  local ok = project():ExportCurrentFrameAsStill(path)
  local tl = timeline()
  return { ok = ok and true or false, path = path, clip = info(tl:GetCurrentVideoItem(), req.target) }
end

function OPS.apply_cdl(req)
  local it = item_for(req.target)
  local node = node_of(req)
  local sat = tonumber(req.saturation or "1")
  assert(sat and sat >= 0 and sat <= 4, "saturation must be 0..4")
  local cdl = {
    NodeIndex = tostring(node), Slope = triple(req.slope, "slope"), Offset = triple(req.offset, "offset"),
    Power = triple(req.power, "power"), Saturation = tostring(sat),
  }
  local prev = ensure_ai_version(it)
  local ok = it:SetCDL(cdl)
  return { ok = ok and true or false, previous_version = prev, clip = info(it, req.target) }
end

-- Resolve may only load LUTs from its own LUT folders (inside the sandbox on the App Store build).
-- Try the file where it is; then copy it into each candidate LUT folder and try again.
local function copy_file(src, dst)
  if bmd.copyfile then
    local ok = pcall(bmd.copyfile, src, dst)
    if ok and (not bmd.fileexists or bmd.fileexists(dst)) then return true end
  end
  local fin = app:OpenFile(src, 1)
  if not fin then return false end
  local fout = app:OpenFile(dst, 2)
  if not fout then fin:Close(); return false end
  for _ = 1, 300000 do
    local line = fin:ReadLine()
    if line == nil then break end
    fout:WriteLine((line:gsub("[\r\n]+$", "")))
  end
  fout:Flush(); fout:Close(); fin:Close()
  return true
end

local function lut_roots()
  local roots = {}
  local ok, fusion_luts = pcall(function() return app:MapPath("LUTs:") end)
  local home = os.getenv("HOME") or ""
  roots[#roots + 1] = home .. "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/"
  roots[#roots + 1] = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/"
  if ok and type(fusion_luts) == "string" then roots[#roots + 1] = fusion_luts end
  return roots
end

function OPS.apply_lut(req)
  local it = item_for(req.target)
  local name = req.lut or ""
  assert(name:match("^[%w][%w _%.%-]*%.cube$") and not name:find("..", 1, true), "invalid LUT file name")
  local path = LUT_DIR .. "/" .. name
  assert(not bmd.fileexists or bmd.fileexists(path), "LUT not found in the resolve-assist LUT folder: " .. name)
  local node = node_of(req)
  local prev = ensure_ai_version(it)
  local graph = it:GetNodeGraph()
  local attempts = {}
  local function try(p, label)
    local ok = graph and graph:SetLUT(node, p)
    if not ok then ok = it:SetLUT(node, p) end
    attempts[#attempts + 1] = label .. ": " .. tostring(ok and true or false)
    return ok
  end
  local ok = try(path, "documents")
  if not ok then
    for _, root in ipairs(lut_roots()) do
      local dst = root .. name
      if copy_file(path, dst) then
        pcall(function() project():RefreshLUTList() end)
        ok = try(dst, root) or try(name, root .. " (relative)")
        if ok then break end
      else
        attempts[#attempts + 1] = root .. ": copy failed"
      end
    end
  end
  local now = graph and graph:GetLUT(node) or it:GetLUT(node)
  return { ok = ok and true or false, lut_now = now, previous_version = prev, attempts = attempts,
           clip = info(it, req.target) }
end

function OPS.stabilize(req)
  local it = item_for(req.target)
  assert(it.Stabilize, "this Resolve build has no Stabilize()")
  local prev = ensure_ai_version(it)
  local ok = it:Stabilize()
  return { ok = ok and true or false, previous_version = prev, clip = info(it, req.target) }
end

function OPS.undo(req)
  local it = item_for(req.target)
  local name = req.version or ""
  assert(name ~= "" and name ~= AI_VERSION, "undo needs the previous version name")
  local ok = it:LoadVersionByName(name, 0)
  return { ok = ok and true or false, clip = info(it, req.target) }
end

function OPS.stop()
  running = false
  return { stopping = true }
end

-- ------------------------------------------------------------------ request loop
local KEYS = { seq = 1, session = 1, ts = 1, op = 1, target = 1, node = 1, slope = 1, offset = 1,
               power = 1, saturation = 1, lut = 1, version = 1 }
local REQUEST = BRIDGE_DIR .. "/request.txt"
local RESPONSE = BRIDGE_DIR .. "/response.txt"
local STATUS = BRIDGE_DIR .. "/status.txt"

local function parse(lines)
  local req = {}
  for _, line in ipairs(lines) do
    local k, v = line:match("^([%w_]+)\t(.*)$")
    if k and KEYS[k] then req[k] = v end
  end
  return req
end

local function current_seq()
  local lines = read_lines(REQUEST, MAX_REQUEST_BYTES)
  return lines and tonumber(parse(lines).seq or "") or 0
end

local last_seq = current_seq()  -- anything already waiting is from an old run: ignore it

local function handle()
  local lines = read_lines(REQUEST, MAX_REQUEST_BYTES)
  if not lines or #lines == 0 then return end
  local req = parse(lines)
  local seq = tonumber(req.seq or "")
  if not seq or not req.seq:match("^%d+$") or seq <= last_seq then return end
  last_seq = seq
  local resp = { seq = req.seq, protocol = PROTOCOL }
  if req.session ~= session then
    resp.ok, resp.error = false, "request from an old bridge session; retry"
  elseif math.abs(os.time() - (tonumber(req.ts) or 0)) > MAX_AGE then
    resp.ok, resp.error = false, "request expired"
  elseif not OPS[req.op or ""] then
    resp.ok, resp.error = false, "operation not allowed: " .. tostring(req.op)
  else
    local ok, result = pcall(OPS[req.op], req)
    resp.ok = ok
    if ok then resp.result = result else resp.error = tostring(result) end
  end
  write_line(RESPONSE, encode(resp))
end

local function install_menu()
  if BRIDGE_INSTALL_MENU == false then return {} end
  local done = {}
  local lines = read_lines(BRIDGE_DIR .. "/loader.lua", 16384)
  local ok, scripts = pcall(function() return app:MapPath("Scripts:") end)
  if not lines or not ok or type(scripts) ~= "string" then return done end
  for _, sub in ipairs({ "Utility", "Color", "Edit" }) do
    local f = app:OpenFile(scripts .. sub .. "/resolve-assist Bridge.lua", 2)
    if f then
      for _, l in ipairs(lines) do f:WriteLine(l) end
      f:Flush(); f:Close()
      done[#done + 1] = sub
    end
  end
  return done
end

local menu = install_menu()

local function heartbeat(state)
  write_line(STATUS, encode({
    session = session, protocol = PROTOCOL, time = os.time(), state = state,
    resolve = r:GetVersionString(), menu = menu,
  }))
end

assert(write_line(STATUS, "{}"), "resolve-assist: cannot write to " .. BRIDGE_DIR)
heartbeat("running")
print("resolve-assist bridge is running (session " .. session .. ").")
print("Leave it running while you work with the AI. Stop: resolve-assist bridge-stop")
if #menu > 0 then print("Next time start it from Workspace > Scripts > " .. menu[1] .. " > resolve-assist Bridge") end

local loops, last_beat = 0, 0
while running do
  local ok, err = pcall(handle)
  if not ok then print("resolve-assist: " .. tostring(err)) end
  local now = os.time()
  if now ~= last_beat then heartbeat("running"); last_beat = now end
  loops = loops + 1
  if MAX_LOOPS and loops >= MAX_LOOPS then break end
  bmd.wait(POLL_SECONDS)
end
heartbeat("stopped")
print("resolve-assist bridge stopped.")
