-- act_dig.lua — set or clear dig designations in a rectangle.
-- PARAMS (set by the Python side): x0,y0,z0,x1,y1,z1, mode.
-- mode is a df.tile_dig_designation name ('Default','Channel','Ramp',
-- 'UpStair','DownStair','UpDownStair') or 'clear'.
-- Set path validates first: every tile must be a solid tile of the
-- shape the mode needs, and nothing is written when any tile fails
-- the check (atomic precondition). The shape is per-mode, not just
-- WALL (verified live 2026-11-26): a down-stair / channel is dug
-- down through a FLOOR (the ground surface a dwarf stands on), while
-- a regular dig / up-stair is dug into a WALL. Requiring WALL for
-- every mode rejected valid down-stairs on the floor and accepted
-- down-stairs on buried soil — which the game then never turns into
-- a Dig job (no dwarf can reach a buried tile to dig it).
-- Prints one JSON object.
local ok, err = pcall(function()
  local mode = PARAMS.mode
  local dig_val = nil
  if mode ~= 'clear' then
    dig_val = df.tile_dig_designation[mode]
    if dig_val == nil then error('unknown dig mode: ' .. tostring(mode)) end
  end
  -- Which tile shapes each mode may be designated on.
  local allowed = {
    Default = {WALL = true},
    Channel = {FLOOR = true},
    Ramp = {WALL = true, FLOOR = true},
    UpStair = {WALL = true},
    DownStair = {FLOOR = true},
    UpDownStair = {WALL = true, FLOOR = true},
  }
  if mode ~= 'clear' then
    local want = allowed[mode] or {}
    local bad = dfh_arr()
    for x = PARAMS.x0, PARAMS.x1 do
      for y = PARAMS.y0, PARAMS.y1 do
        local b = dfhack.maps.getTileBlock(x, y, PARAMS.z0)
        local tt = b.tiletype[x % 16][y % 16]
        local shape = tostring(df.tiletype_shape[df.tiletype.attrs[tt].shape])
        if not want[shape] then
          if #bad < 10 then bad[#bad+1] = dfh_arr({x, y, shape}) end
        end
      end
    end
    if #bad > 0 then
      result = {ok = false, action = 'dig', kind = 'precondition',
        error = 'not all tiles are a valid shape for ' .. mode,
        bad_tiles = bad}
      return
    end
  end
  local set_n, cleared_n = 0, 0
  for x = PARAMS.x0, PARAMS.x1 do
    for y = PARAMS.y0, PARAMS.y1 do
      local b = dfhack.maps.getTileBlock(x, y, PARAMS.z0)
      local d = b.designation[x % 16][y % 16]
      if mode == 'clear' then
        if d.dig ~= 0 then cleared_n = cleared_n + 1 end
        d.dig = df.tile_dig_designation.No
      else
        d.dig = dig_val
        set_n = set_n + 1
      end
    end
  end
  result = {ok = true, action = 'dig', mode = mode,
    set = set_n, cleared = cleared_n}
end)
if not ok then
  result = {ok = false, action = 'dig', error = tostring(err)}
end
dfh_print(result)
