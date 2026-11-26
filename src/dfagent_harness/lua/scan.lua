-- scan.lua — full map-block scan for the spatial model (design §3.3/§3.5).
-- Emits, per block (16x16 tiles), three bitmasks as run-length arrays:
--   open: the block contains any walkable tile (floor/pebbles/ramp/
--     stair/brook-bed) — the connectivity graph's nodes.
--   up:   the block contains a ramp or an up-stair (connects upward).
--   down: the block contains a ramp or a down-stair (connects downward).
-- A ramp counts as both up and down. Blocks are indexed
-- (z * y_blocks + by) * x_blocks + bx, in row-major block order.
-- The bitmasks are run-length encoded (runs alternate 0/1, starting
-- with a 0-run) so the transfer stays ~1 KB instead of one JSON
-- object per block (the encoder is gsub-based; per-block JSON would
-- be slow and huge). SLOW: one full pass over every block x tile
-- (~10-15 s on a 192x192x197 map); cached by the Python side, never
-- per tick. Prints one JSON object.
local ok, err = pcall(function()
  local t0 = os.clock()
  local m = df.global.world.map
  local xb, yb = m.x_count // 16, m.y_count // 16
  local zc = m.z_count
  local total = xb * yb * zc
  local open = {}
  local up = {}
  local down = {}
  for i = 1, total do open[i] = 0; up[i] = 0; down[i] = 0 end
  local OPEN = {FLOOR = true, PEBBLES = true, RAMP = true,
    STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true,
    BROOK_BED = true}
  -- Classify a tiletype once (bits: 1 = open, 2 = connects up,
  -- 4 = connects down). The attrs + enum + tostring chain per tile
  -- is ~50 us, so 7.2M tiles would take ~9 min; the cache makes it
  -- once per distinct tiletype (a handful per map).
  local class_cache = {}
  local function classify(tt)
    local c = class_cache[tt]
    if c ~= nil then return c end
    local shape = tostring(
      df.tiletype_shape[df.tiletype.attrs[tt].shape])
    c = 0
    if OPEN[shape] then
      c = 1
      if shape == 'RAMP' or shape == 'STAIR_UP'
        or shape == 'STAIR_UPDOWN' then c = c + 2 end
      if shape == 'RAMP' or shape == 'STAIR_DOWN'
        or shape == 'STAIR_UPDOWN' then c = c + 4 end
    end
    class_cache[tt] = c
    return c
  end
  for _, blk in ipairs(m.map_blocks) do
    -- map_pos is in TILE coordinates (the block's origin tile), not
    -- block units: divide x/y by 16 to get the block index. z is
    -- already the block's z-level. (Found live 2026-11-26: using
    -- map_pos raw put every open bit at a wrong index.)
    local bx, by, bz = blk.map_pos.x // 16, blk.map_pos.y // 16,
      blk.map_pos.z
    local idx = (bz * yb + by) * xb + bx + 1
    local is_open, has_up, has_down = false, false, false
    for x = 0, 15 do
      for y = 0, 15 do
        local c = classify(blk.tiletype[x][y])
        if c % 2 == 1 then
          is_open = true
          if c % 4 >= 2 then has_up = true end
          if c >= 4 then has_down = true end
          if has_up and has_down then break end
        end
      end
      if is_open and has_up and has_down then break end
    end
    if is_open then open[idx] = 1 end
    if has_up then up[idx] = 1 end
    if has_down then down[idx] = 1 end
  end
  local function rle(bits)
    local runs = dfh_arr()
    local cur, n = 0, 0
    for i = 1, total do
      if bits[i] == cur then n = n + 1
      else runs[#runs + 1] = n; cur = bits[i]; n = 1 end
    end
    runs[#runs + 1] = n
    return runs
  end
  local open_count = 0
  for i = 1, total do open_count = open_count + open[i] end
  result = {ok = true, scan = {
    x_blocks = xb, y_blocks = yb, z_count = zc,
    x_count = m.x_count, y_count = m.y_count,
    total_blocks = total, open_blocks = open_count,
    open_rle = rle(open), up_rle = rle(up), down_rle = rle(down),
    scan_seconds = os.clock() - t0,
  }}
end)
if not ok then
  result = {ok = false, scan = 'full', error = tostring(err)}
end
dfh_print(result)
