-- column.lua — vertical profile of one map column (x, y).
-- Standing directive 2026-11-26 (vertical awareness): the agent must
-- be able to ask "what is underneath this spot before I dig there?"
-- Walks the full column from the top z down to 0, classifies each
-- tile, and aggregates consecutive same-class tiles into strata.
-- Classes: soil, stone, mineral, aquifer (solid + water_table bit),
-- water, magma, floor, passage (ramp/stair), air, plant. Each run
-- also carries ``unrevealed``: true when no dwarf has seen the
-- tiles in it. Hazards and geology are read even on unrevealed
-- tiles (the column is a planning probe, like the survey) — the
-- unrevealed flag is what keeps the agent honest about it.
-- The Python side merges floor/passage/air runs into "open space"
-- and labels tall open runs below the surface as cavern space.
-- Cheap: one getTileBlock per z-level (~197), ~50 ms. Prints one
-- JSON object.
local ok, err = pcall(function()
  local t0 = os.clock()
  local m = df.global.world.map
  local x, y = PARAMS.x, PARAMS.y
  if x < 0 or y < 0 or x >= m.x_count or y >= m.y_count then
    -- A bad coordinate is a caller error, not a helper failure:
    -- report it inside the column so read_column raises ValueError
    -- (the route answers 400) instead of a 503.
    result = {ok = true, column = {ok = false,
      error = 'column out of map bounds'}}
    return
  end
  local info_cache = {}
  local function tile_info(tt)
    local info = info_cache[tt]
    if info then return info end
    local attrs = df.tiletype.attrs[tt]
    local mat = tostring(df.tiletype_material[attrs.material])
    local shape = tostring(df.tiletype_shape[attrs.shape])
    info = {mat = mat, shape = shape,
            solid = (shape == 'WALL' or shape == 'FORTIFICATION')}
    info_cache[tt] = info
    return info
  end
  -- Classify one tile. Hazards and geology are read from the map
  -- data (designation + tiletype) EVEN WHEN the tile is unrevealed:
  -- the column's job is to answer "what will I hit if I dig here?",
  -- and Mikey's directive is explicit that the agent must know
  -- about lava below or an aquifer above. The survey already reads
  -- the same data (it found the aquifer at z164 on hidden rock).
  -- What the tile being hidden DOES mean is recorded separately:
  -- each run carries ``unrevealed`` (true when no dwarf has seen
  -- any tile in it), so the agent knows the ground is map data,
  -- not something a dwarf has seen. This is NOT the slice's
  -- hidden-tile rule (design §3.4, the agent's eyes) — the column
  -- is a planning probe, like the survey.
  local function classify(tt, d)
    local hidden = d.hidden
    if d.flow_size > 0 then
      return d.liquid_type and 'magma' or 'water', d.flow_size,
        hidden
    end
    local info = tile_info(tt)
    if info.solid then
      if d.water_table then return 'aquifer', 0, hidden end
      if info.mat == 'MINERAL' then return 'mineral', 0, hidden end
      if info.mat == 'SOIL' then return 'soil', 0, hidden end
      return 'stone', 0, hidden
    end
    if info.shape == 'FLOOR' or info.shape == 'PEBBLES'
      or info.shape == 'BROOK_BED' then return 'floor', 0, hidden end
    if info.shape == 'RAMP' or info.shape == 'STAIR_UP'
      or info.shape == 'STAIR_DOWN' or info.shape == 'STAIR_UPDOWN'
      then return 'passage', 0, hidden end
    if info.shape == 'TREE' or info.shape == 'SHRUB'
      or info.shape == 'SAPLING' then return 'plant', 0, hidden end
    return 'air', 0, hidden
  end
  -- Walk top-down, aggregating runs of the same class AND the same
  -- revealed state (a revealed run and an unrevealed run of the
  -- same class are different knowledge and must not merge).
  local strata = dfh_arr()
  local cur = nil
  local bx, by = x // 16, y // 16
  local lx, ly = x % 16, y % 16
  for z = m.z_count - 1, 0, -1 do
    local blk = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
    local class, depth, hidden = 'hidden', 0, true
    if blk then
      class, depth, hidden = classify(blk.tiletype[lx][ly],
                                      blk.designation[lx][ly])
    end
    if cur and cur.class == class and cur.unrevealed == hidden then
      cur.z0 = z
      if depth > cur.max_depth then cur.max_depth = depth end
    else
      if cur then strata[#strata+1] = cur end
      cur = {class = class, z1 = z, z0 = z, max_depth = depth,
             unrevealed = hidden}
    end
  end
  if cur then strata[#strata+1] = cur end
  result = {ok = true, column = {
    x = x, y = y, z_count = m.z_count,
    strata = strata,
    cost_ms = math.floor((os.clock() - t0) * 1000),
  }}
end)
if not ok then
  result = {ok = false, column = 'profile', error = tostring(err)}
end
dfh_print(result)
