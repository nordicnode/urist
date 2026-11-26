-- survey.lua — resource survey: one full block scan, aggregates per
-- kind (design §5.1). Emits counts + locations, never per-tile JSON.
--   water / magma: sparse per-block {block_idx, tiles, max_depth}
--     (flow_size > 0; liquid_type false = water, true = magma).
--     Verified live 2026-11-26: flow_size + liquid_type are the
--     fields; a pool sits at z=174, (162,122), flow 7.
--   mineral: sparse per-block {block_idx, tiles} where the tiletype
--     material is MINERAL. The specific ore is NOT in the tiletype
--     (design §5.1 fallback): veins report as "mineral vein
--     (unidentified)".
--   aquifer: per-z counts of BLOCKS whose sampled corners show the
--     designation's water_table bit on solid soil/stone (a 4-corner
--     sample per block; an aquifer is a layer phenomenon). Aquifer
--     water shows no flow_size until the rock is exposed. Light vs
--     heavy is NOT measurable from tile data: the site's aquifer is
--     "light" per the embark warning, and that label is reported
--     with the measured z-levels, not inferred.
--   soil / stone: per-z counts (they are everywhere; a sparse list
--     would be huge). Specific stone identity has the same caveat
--     as ore.
--   plants: per species (raws.plants.all[material].id/name), count,
--     bbox, z-range, shrub vs tree. Gatherable shrubs are flagged.
-- SLOW: one full pass (~10-15 s on 192x192x197); cached by the
-- Python side per kind, never per tick. The designation read is
-- skipped for solid (WALL) tiles — water cannot sit in solid rock —
-- which is most of the map. Prints one JSON object.
local ok, err = pcall(function()
  local t0 = os.clock()
  local m = df.global.world.map
  local xb, yb = m.x_count // 16, m.y_count // 16
  local zc = m.z_count
  -- One cache per tiletype: material class + whether it is solid.
  -- (The attrs + enum + tostring chain is ~50 us; uncached, 7.2M
  -- tiles would take ~9 min — see scan.lua.)
  local info_cache = {}
  local function tile_info(tt)
    local info = info_cache[tt]
    if info then return info end
    local attrs = df.tiletype.attrs[tt]
    local mat = tostring(df.tiletype_material[attrs.material])
    local shape = tostring(df.tiletype_shape[attrs.shape])
    info = {mat = mat,
            solid = (shape == 'WALL' or shape == 'FORTIFICATION')}
    info_cache[tt] = info
    return info
  end
  local water_blocks = dfh_arr()
  local magma_blocks = dfh_arr()
  local mineral_blocks = dfh_arr()
  local soil_by_z = dfh_arr()
  local stone_by_z = dfh_arr()
  local aquifer_by_z = dfh_arr()
  for i = 1, zc do soil_by_z[i] = 0; stone_by_z[i] = 0;
    aquifer_by_z[i] = 0 end
  local water_total, magma_total, mineral_total = 0, 0, 0
  local aquifer_total = 0  -- blocks showing aquifer (sampled)
  for _, blk in ipairs(m.map_blocks) do
    -- map_pos is in TILE coordinates (see scan.lua): divide by 16.
    local bx, by, bz = blk.map_pos.x // 16, blk.map_pos.y // 16,
      blk.map_pos.z
    local idx = (bz * yb + by) * xb + bx
    local w_tiles, w_max = 0, 0
    local mg_tiles, mg_max = 0, 0
    local mn_tiles = 0
    local so_tiles, st_tiles = 0, 0
    for x = 0, 15 do
      for y = 0, 15 do
        local tt = blk.tiletype[x][y]
        local info = tile_info(tt)
        if info.mat == 'MINERAL' then mn_tiles = mn_tiles + 1
        elseif info.mat == 'SOIL' then so_tiles = so_tiles + 1
        elseif info.mat == 'STONE' then st_tiles = st_tiles + 1 end
        if not info.solid then
          local d = blk.designation[x][y]
          if d.flow_size > 0 then
            if d.liquid_type then
              mg_tiles = mg_tiles + 1
              if d.flow_size > mg_max then mg_max = d.flow_size end
            else
              w_tiles = w_tiles + 1
              if d.flow_size > w_max then w_max = d.flow_size end
            end
          end
        end
      end
    end
    -- Aquifer: sampled, NOT per tile. A per-tile designation read
    -- on all ~5.3M solid tiles wedged DF for 180 s+ (the designation
    -- proxy access is ~30 us; the first attempt never returned and
    -- the game had to be killed and reloaded from the save). An
    -- aquifer is a layer phenomenon, so 4 corner samples per block
    -- are enough to say which z-levels carry one. The water_table
    -- bit reads directly (no pcall per tile); it was verified to
    -- read cleanly on this build.
    local aq_hits = 0
    for _, s in ipairs({{0, 0}, {15, 0}, {0, 15}, {15, 15}}) do
      local sx, sy = s[1], s[2]
      local tt = blk.tiletype[sx][sy]
      local info = tile_info(tt)
      if info.solid and (info.mat == 'SOIL' or info.mat == 'STONE')
        and blk.designation[sx][sy].water_table then
        aq_hits = aq_hits + 1
      end
    end
    if aq_hits > 0 then
      aquifer_by_z[bz + 1] = aquifer_by_z[bz + 1] + 1
      aquifer_total = aquifer_total + 1
    end
    if w_tiles > 0 then
      water_blocks[#water_blocks+1] = {idx = idx, tiles = w_tiles,
        max_depth = w_max, z = bz}
      water_total = water_total + w_tiles
    end
    if mg_tiles > 0 then
      magma_blocks[#magma_blocks+1] = {idx = idx, tiles = mg_tiles,
        max_depth = mg_max, z = bz}
      magma_total = magma_total + mg_tiles
    end
    if mn_tiles > 0 then
      mineral_blocks[#mineral_blocks+1] = {idx = idx, tiles = mn_tiles,
        z = bz}
      mineral_total = mineral_total + mn_tiles
    end
    soil_by_z[bz + 1] = soil_by_z[bz + 1] + so_tiles
    stone_by_z[bz + 1] = stone_by_z[bz + 1] + st_tiles
  end
  -- Plants: per species, from world.plants.all (cheap; not a scan).
  -- Nearest per species is computed here against PARAMS fx/fy/fz
  -- (the fort centre): a species bbox spans the whole map, so a
  -- bbox-clamped "nearest" would wrongly read 0 tiles away whenever
  -- the fort sits inside the bbox.
  local fx = (PARAMS and PARAMS.fx) or 97
  local fy = (PARAMS and PARAMS.fy) or 97
  local fz = (PARAMS and PARAMS.fz) or 175
  local species = {}
  for _, p in ipairs(df.global.world.plants.all) do
    local mat = p.material
    local rec = species[mat]
    if rec == nil then
      local raw = df.global.world.raws.plants.all[mat]
      local id = dfh_try(function() return raw.id end, 'unknown')
      local name = dfh_try(function() return raw.name end, id)
      rec = {species = id, name = name,
             is_shrub = p.flags.is_shrub, count = 0,
             x0 = p.pos.x, y0 = p.pos.y, z0 = p.pos.z,
             x1 = p.pos.x, y1 = p.pos.y, z1 = p.pos.z,
             nearest_dist = 1000000, nearest_pos = nil}
      species[mat] = rec
    end
    rec.count = rec.count + 1
    local d = math.max(math.abs(p.pos.x - fx),
                       math.abs(p.pos.y - fy),
                       math.abs(p.pos.z - fz))
    if d < rec.nearest_dist then
      rec.nearest_dist = d
      rec.nearest_pos = dfh_arr({p.pos.x, p.pos.y, p.pos.z})
    end
    if p.pos.x < rec.x0 then rec.x0 = p.pos.x end
    if p.pos.y < rec.y0 then rec.y0 = p.pos.y end
    if p.pos.z < rec.z0 then rec.z0 = p.pos.z end
    if p.pos.x > rec.x1 then rec.x1 = p.pos.x end
    if p.pos.y > rec.y1 then rec.y1 = p.pos.y end
    if p.pos.z > rec.z1 then rec.z1 = p.pos.z end
  end
  local species_list = dfh_arr()
  for _, rec in pairs(species) do species_list[#species_list+1] = rec end
  table.sort(species_list, function(a, b) return a.count > b.count end)
  result = {ok = true, survey = {
    x_blocks = xb, y_blocks = yb, z_count = zc,
    x_count = m.x_count, y_count = m.y_count,
    water_blocks = water_blocks, water_total = water_total,
    magma_blocks = magma_blocks, magma_total = magma_total,
    mineral_blocks = mineral_blocks, mineral_total = mineral_total,
    aquifer_total = aquifer_total,  -- blocks (sampled), not tiles
    aquifer_by_z = aquifer_by_z,
    soil_by_z = soil_by_z, stone_by_z = stone_by_z,
    plants = species_list,
    scan_seconds = os.clock() - t0,
  }}
end)
if not ok then
  result = {ok = false, survey = 'full', error = tostring(err)}
end
dfh_print(result)
