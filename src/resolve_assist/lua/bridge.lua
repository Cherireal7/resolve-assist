--[[
resolve-assist bridge (Phase 2), protocol 7

Runs inside DaVinci Resolve (Free or Studio). Started by the loader that
`resolve-assist bridge-install` puts on your clipboard, or from the Scripts menu
after the first run. It talks to the resolve-assist server through files in a
shared folder (works in the sandboxed Mac App Store build: uses fu:OpenFile,
no io library needed).

Security:
- Only the operations in OPS below can run. Request data is NEVER executed.
- Requests must carry this run's session id and be fresh (MAX_AGE seconds).
- LUTs are only loaded from the resolve-assist LUT folder; music only from its media folder.
- Edits (music, titles) only happen on a copy of the timeline named "... (resolve-assist)".
- Before the first change on a clip it switches to a separate grade version
  named "resolve-assist", so your own grade is untouched and undo is one click.
]]

local BRIDGE_DIR = BRIDGE_DIR_OVERRIDE or {{BRIDGE_DIR}}
local LUT_DIR = LUT_DIR_OVERRIDE or {{LUT_DIR}}
local MEDIA_DIR = MEDIA_DIR_OVERRIDE or {{MEDIA_DIR}}
local LIBRARY_DIR = LIBRARY_DIR_OVERRIDE or {{LIBRARY_DIR}}
local PROTOCOL = 7
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


-- ------------------------------------------------------------------ editing (on a timeline copy only)
local COPY_TAG = "(resolve-assist)"

local function is_copy(tl) return tl:GetName():find(COPY_TAG, 1, true) ~= nil end

function OPS.duplicate_timeline()
  local p, tl = project(), timeline()
  local name = tl:GetName()
  if is_copy(tl) then return { timeline = name, created = false } end
  local copy_name = name .. " " .. COPY_TAG
  for i = 1, p:GetTimelineCount() do
    local t = p:GetTimelineByIndex(i)
    if t and t:GetName() == copy_name then
      assert(p:SetCurrentTimeline(t), "could not open " .. copy_name)
      return { timeline = copy_name, created = false, original = name }
    end
  end
  local dup = tl:DuplicateTimeline(copy_name)
  assert(dup, "could not duplicate the timeline")
  assert(p:SetCurrentTimeline(dup), "could not open the timeline copy")
  return { timeline = copy_name, created = true, original = name }
end

local AUDIO_EXT = { mp3 = true, wav = true, m4a = true, aac = true, aif = true, aiff = true }

function OPS.add_music(req)
  local tl = timeline()
  assert(is_copy(tl), "edits only happen on the resolve-assist copy of the timeline")
  local name = req.file or ""
  assert(name:match("^[%w][%w _%.%-]*%.%w+$") and not name:find("..", 1, true), "invalid file name")
  assert(AUDIO_EXT[name:match("%.(%w+)$"):lower()], "music must be mp3, wav, m4a, aac or aiff")
  local path = MEDIA_DIR .. "/" .. name
  assert(not bmd.fileexists or bmd.fileexists(path), "music not found in the resolve-assist media folder: " .. name)
  local mp = project():GetMediaPool()
  local imported = mp:ImportMedia({ path })
  assert(imported and imported[1], "Resolve could not import " .. name)
  local audio = imported[1]
  if tl:GetTrackCount("audio") < 2 then tl:AddTrack("audio", "stereo") end
  local track = tl:GetTrackCount("audio")
  local first, last = tl:GetStartFrame(), tl:GetEndFrame()
  local stop = last - first - 1
  local frames = tonumber(audio:GetClipProperty("Frames") or "")
  if frames and frames > 0 then stop = math.min(stop, frames - 1) end
  local placed = mp:AppendToTimeline({ { mediaPoolItem = audio, startFrame = 0, endFrame = stop,
                                         mediaType = 2, trackIndex = track, recordFrame = first } })
  assert(placed and placed[1], "Resolve could not place the music on the timeline")
  return { ok = true, file = name, audio_track = track, frames = stop + 1, timeline = tl:GetName() }
end

-- Titles are composited INSIDE the clip with Fusion (Text+ over MediaIn), so the timeline
-- structure never changes. (Timeline:InsertFusionTitleIntoTimeline did an insert edit on
-- video track 1 in Free 21.2 and split the clip: not used.)
function OPS.add_title(req)
  local tl = timeline()
  assert(is_copy(tl), "edits only happen on the resolve-assist copy of the timeline")
  local text = req.text or ""
  assert(#text >= 1 and #text <= 200, "text must be 1..200 characters")
  local at = tonumber(req.at or "0")
  assert(at and at >= 0 and at < 36000, "at must be seconds from the start")
  local dur = tonumber(req.duration or "5")
  assert(dur and dur > 0 and dur <= 600, "duration must be 0..600 seconds")
  local it = item_for((req.target and req.target ~= "") and req.target or "1:1")
  local comp = (it:GetFusionCompCount() > 0) and it:GetFusionCompByIndex(1) or it:AddFusionComp()
  assert(comp, "could not open the clip's Fusion composition")
  local mo = comp:FindTool("MediaOut1")
  assert(mo, "the clip's composition has no MediaOut1")
  comp:Lock()
  local ok, err = pcall(function()
    local txt = comp:FindTool("RA_Title")
    if not txt then txt = comp:AddTool("TextPlus", -32768, -32768); txt:SetAttrs({ TOOLS_Name = "RA_Title" }) end
    local mg = comp:FindTool("RA_TitleMerge")
    if not mg then
      mg = comp:AddTool("Merge", -32768, -32768); mg:SetAttrs({ TOOLS_Name = "RA_TitleMerge" })
      local main = (mo.FindMainInput and mo:FindMainInput(1)) or mo.Input
      local upstream = main and main:GetConnectedOutput()
      if upstream then mg:ConnectInput("Background", upstream) end
      mg:ConnectInput("Foreground", txt)
      mo:ConnectInput("Input", mg)
    end
    txt:SetInput("StyledText", (text:gsub("|", "\n")))
    txt:SetInput("Size", 0.05)
    txt:SetInput("Center", { 0.5, 0.86 })
  end)
  -- Timing: keyframes are relative to the comp's RenderStart (GlobalStart can be the source timecode).
  local timed, attrs = false, {}
  pcall(function()
    for _, k in ipairs({ "GlobalStart", "GlobalEnd", "RenderStart", "RenderEnd" }) do
      attrs[k] = comp:GetAttrs("COMPN_" .. k)
    end
  end)
  if ok then
    local mg = comp:FindTool("RA_TitleMerge")
    local fps = fps_of(tl)
    local clip_s = (it:GetEnd() - it:GetStart()) / fps
    if at <= 0 and at + dur >= clip_s then
      pcall(function() mg:ConnectInput("Blend", nil); mg:SetInput("Blend", 1) end)  -- whole clip: no animation
    else
      timed = pcall(function()
        local t0 = tonumber(attrs.RenderStart) or 0
        local a = t0 + math.floor(at * fps)
        local b = a + math.floor(dur * fps)
        local fade = math.max(1, math.floor(0.4 * fps))
        mg:ConnectInput("Blend", nil)
        mg.Blend = comp:BezierSpline({})
        mg.Blend[math.max(t0, a - 1)] = 0
        mg.Blend[a + fade] = 1
        mg.Blend[b - fade] = 1
        mg.Blend[b] = 0
      end)
    end
  end
  local tools = {}
  pcall(function()
    for _, t in pairs(comp:GetToolList(false) or {}) do tools[#tools + 1] = t.Name end
    table.sort(tools)
  end)
  comp:Unlock()
  assert(ok, "could not build the title: " .. tostring(err))
  return { ok = true, text = text, at = at, duration = dur, timed = timed, clip = info(it), timeline = tl:GetName(),
           comp = { attrs = attrs, tools = tools, count = it:GetFusionCompCount() } }
end

-- Delete a timeline copy made by resolve-assist (never the original) and go back to the original.
function OPS.reset_copy()
  local p, tl = project(), timeline()
  if not is_copy(tl) then return { deleted = false, reason = "current timeline is not a resolve-assist copy" } end
  local original = tl:GetName():gsub(" %(resolve%-assist%)$", "")
  local orig = nil
  for i = 1, p:GetTimelineCount() do
    local t = p:GetTimelineByIndex(i)
    if t and t:GetName() == original then orig = t end
  end
  assert(orig, "original timeline '" .. original .. "' not found; the copy is kept")
  assert(p:SetCurrentTimeline(orig), "could not open the original timeline")
  local deleted = p:GetMediaPool():DeleteTimelines({ tl })
  return { deleted = deleted and true or false, original = original }
end


-- ------------------------------------------------------------------ asset library
local function library_path(rel)
  assert(type(rel) == "string" and rel:match("^[%w][%w _%.%-/]*$") and not rel:find("..", 1, true)
         and not rel:find("//", 1, true), "invalid library path: " .. tostring(rel))
  local path = LIBRARY_DIR .. "/" .. rel
  assert(not bmd.fileexists or bmd.fileexists(path), "not in the library: " .. rel)
  return path
end

function OPS.import_media(req)
  local files = {}
  for rel in (req.files or ""):gmatch("[^|]+") do files[#files + 1] = library_path(rel) end
  assert(#files >= 1 and #files <= 30, "give 1..30 library files")
  local mp = project():GetMediaPool()
  local root = mp:GetRootFolder()
  local bin = nil
  for _, f in ipairs(root:GetSubFolderList() or {}) do
    if f:GetName() == "resolve-assist library" then bin = f end
  end
  bin = bin or mp:AddSubFolder(root, "resolve-assist library")
  assert(bin, "could not create the Media Pool bin")
  local before = mp:GetCurrentFolder()
  mp:SetCurrentFolder(bin)
  local items = mp:ImportMedia(files) or {}
  if before then mp:SetCurrentFolder(before) end
  local names = {}
  for _, it in ipairs(items) do names[#names + 1] = it:GetName() end
  return { ok = #names > 0, imported = names, bin = "resolve-assist library" }
end

function OPS.apply_drx(req)
  local it = item_for(req.target)
  local rel = req.file or ""
  assert(rel:match("^powergrades/[%w][%w _%.%-]*%.drx$"), "PowerGrades must be .drx files in library/powergrades")
  local path = library_path(rel)
  local mode = tonumber(req.mode or "0") or 0
  assert(mode >= 0 and mode <= 2, "mode must be 0 (no keyframes), 1 (source timecode) or 2 (start frames)")
  local prev = ensure_ai_version(it)
  local graph = it:GetNodeGraph()
  local ok = graph and graph:ApplyGradeFromDRX(path, mode)
  return { ok = ok and true or false, previous_version = prev, nodes = it:GetNumNodes(), clip = info(it, req.target) }
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
               power = 1, saturation = 1, lut = 1, version = 1, file = 1, text = 1, at = 1, duration = 1, files = 1, mode = 1 }
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
