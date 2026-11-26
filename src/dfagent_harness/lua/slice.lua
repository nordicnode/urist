-- slice.lua — text map of a rectangle on one z-level (the agent's eyes).
-- World-model design §3.4. PARAMS: x0,y0,z,x1,y1,layer.
-- Layers: terrain (default), water, designations, buildings, units.
-- The alphabet (ASCII only): '#' wall, '.' floor, ',' pebbles, '_' ramp,
-- '<' up-stair, '>' down-stair, 'X' up/down stair, '+' closed door,
-- '=' bridge, '"' grate, '^' trap, '~' water, '!' magma, 'T' tree,
-- '*' shrub/plant, 'o' boulder/loose stone, 'B' building, 'D' dig
-- designation, 'S' smoothed/engraved, ' ' open air / hidden tile.
-- Hidden tiles render blank (no seeing through unrevealed rock) and
-- are counted in the summary. Prints one JSON object.
local ok, err = pcall(function()
  local t0 = os.clock()
  local m = df.global.world.map
  local x0, y0, z = PARAMS.x0, PARAMS.y0, PARAMS.z
  local x1, y1 = PARAMS.x1, PARAMS.y1
  local layer = PARAMS.layer or 'terrain'
  if x0 < 0 or y0 < 0 or x1 >= m.x_count or y1 >= m.y_count
    or z < 0 or z >= m.z_count or x1 < x0 or y1 < y0 then
    result = {ok = false, slice = 'bounds',
      error = 'rect out of map bounds'}
    return
  end
  local valid_layers = {terrain = true, water = true,
    designations = true, buildings = true, units = true}
  if not valid_layers[layer] then
    result = {ok = false, slice = 'layer',
      error = 'unknown layer: ' .. tostring(layer)}
    return
  end
  -- Plants in the rect (trees vs shrubs), by position.
  local plants = {}
  for _, p in ipairs(df.global.world.plants.all) do
    if p.pos.z == z and p.pos.x >= x0 and p.pos.x <= x1
      and p.pos.y >= y0 and p.pos.y <= y1 then
      plants[p.pos.x .. ',' .. p.pos.y] = p.flags.is_shrub and '*' or 'T'
    end
  end
  -- Buildings in the rect (footprint by bbox overlap).
  local buildings = {}
  for _, bd in ipairs(df.global.world.buildings.all) do
    if bd.z == z and bd.x2 >= x0 and bd.x1 <= x1
      and bd.y2 >= y0 and bd.y1 <= y1 then
      local btype = tostring(df.building_type[bd:getType()])
      for x = math.max(bd.x1, x0), math.min(bd.x2, x1) do
        for y = math.max(bd.y1, y0), math.min(bd.y2, y1) do
          buildings[x .. ',' .. y] = btype .. ' #' .. bd.id
        end
      end
    end
  end
  -- Units in the rect (active units only). Citizens read 'd'; other
  -- units read 'u' here — the Python side refines the class (it has
  -- the full unit records from observe).
  local units = {}
  for _, u in ipairs(df.global.world.units.active) do
    if u.pos.z == z and u.pos.x >= x0 and u.pos.x <= x1
      and u.pos.y >= y0 and u.pos.y <= y1 then
      local is_citizen = false
      pcall(function() is_citizen = dfhack.units.isCitizen(u) end)
      local name = dfhack.TranslateName(
        dfhack.units.getVisibleName(u))
      if name == '' then
        name = dfhack.units.getRaceName(u) or 'unit'
      end
      units[u.pos.x .. ',' .. u.pos.y] = {
        char = is_citizen and 'd' or 'u', id = u.id, name = name}
    end
  end
  -- Glyph for one tile's shape/material, cached by tiletype number
  -- (the attrs + enum + tostring chain per tile is the slow part).
  local glyph_cache = {}
  local function shape_glyph(tt)
    local g = glyph_cache[tt]
    if g then return g end
    local attrs = df.tiletype.attrs[tt]
    local shape = tostring(df.tiletype_shape[attrs.shape])
    if shape == 'WALL' then g = '#'
    elseif shape == 'FLOOR' then g = '.'
    elseif shape == 'PEBBLES' then g = ','
    elseif shape == 'RAMP' then g = '_'
    elseif shape == 'STAIR_UP' then g = '<'
    elseif shape == 'STAIR_DOWN' then g = '>'
    elseif shape == 'STAIR_UPDOWN' then g = 'X'
    elseif shape == 'BROOK_BED' then g = '.'
    elseif shape == 'BROOK_TOP' then g = '~'
    elseif shape == 'FORTIFICATION' then g = '#'
    elseif shape == 'BOULDER' then g = 'o'
    elseif shape == 'TREE' then g = 'T'
    elseif shape == 'SHRUB' then g = '*'
    elseif shape == 'SAPLING' then g = '*'
    else g = '#' end
    glyph_cache[tt] = g
    return g
  end
  local grid = dfh_arr()
  local counts = {}
  local hidden = 0
  local function bump(g)
    counts[g] = (counts[g] or 0) + 1
  end
  -- Block cache: one getTileBlock per 16x16 block, not per tile.
  local cur_bx, cur_by, cur_b = nil, nil, nil
  local function block_at(x, y)
    local bx, by = x // 16, y // 16
    if bx ~= cur_bx or by ~= cur_by then
      cur_bx, cur_by = bx, by
      cur_b = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
    end
    return cur_b
  end
  for y = y0, y1 do
    local row = {}
    for x = x0, x1 do
      local key = x .. ',' .. y
      local b = block_at(x, y)
      local lx, ly = x % 16, y % 16
      local d = b.designation[lx][ly]
      local g
      if d.hidden then
        g = ' '
        hidden = hidden + 1
      elseif layer == 'water' then
        if d.flow_size > 0 then
          g = d.liquid_type and '!' or '~'
        else
          g = ' '
        end
      elseif layer == 'designations' then
        if d.dig ~= 0 then g = 'D'
        elseif d.smooth ~= 0 then g = 'S'
        else g = ' ' end
      elseif layer == 'buildings' then
        g = buildings[key] and 'B' or ' '
      else
        -- terrain / units: water and magma first, then the tile.
        if d.flow_size > 0 then
          g = d.liquid_type and '!' or '~'
        elseif plants[key] then
          g = plants[key]
        elseif buildings[key] then
          g = 'B'
        else
          local tt = b.tiletype[lx][ly]
          g = shape_glyph(tt)
        end
        if layer == 'units' and units[key] then
          g = units[key].char
        end
      end
      row[#row + 1] = g
      bump(g)
    end
    grid[#grid + 1] = table.concat(row)
  end
  -- Markers: units and buildings of interest in the rect.
  local markers = dfh_arr()
  for key, u in pairs(units) do
    local x, y = key:match('^(%d+),(%d+)$')
    markers[#markers + 1] = {char = u.char, x = tonumber(x),
      y = tonumber(y), what = u.name .. ' (unit #' .. u.id .. ')'}
  end
  local seen_b = {}
  for key, btype in pairs(buildings) do
    if not seen_b[btype] then
      seen_b[btype] = true
      local x, y = key:match('^(%d+),(%d+)$')
      markers[#markers + 1] = {char = 'B', x = tonumber(x),
        y = tonumber(y), what = btype}
    end
  end
  local count_list = dfh_arr()
  for g, n in pairs(counts) do
    count_list[#count_list + 1] = {glyph = g, count = n}
  end
  table.sort(count_list, function(a, b) return a.count > b.count end)
  result = {ok = true, slice = {
    bbox = {x0 = x0, y0 = y0, z = z, x1 = x1, y1 = y1},
    layer = layer,
    grid = grid,
    markers = markers,
    counts = count_list,
    hidden = hidden,
    cost_ms = math.floor((os.clock() - t0) * 1000),
  }}
end)
if not ok then
  result = {ok = false, slice = 'render', error = tostring(err)}
end
dfh_print(result)
