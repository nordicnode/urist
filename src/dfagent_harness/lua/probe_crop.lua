-- probe_crop.lua — the farming facts for one crop (plant raw).
-- Resolves a crop raw id (e.g. MUSHROOM_HELMET_PLUMP) to its live
-- facts, so the crop-setting action can verify a planting BEFORE
-- it writes anything. All field names verified live 2026-11-27 on
-- the scratch fort (region5): plant raws carry underground_depth
-- min/max, growdur, and SPRING/SUMMER/AUTUMN/WINTER + BIOME_* as
-- flags; the tile biome comes from the map-block designation
-- (designation.biome, a biome_type value) and the flag name is
-- "BIOME_" .. biome_type name, positionally exact (verified:
-- tile biome 4 = SWAMP_TEMPERATE_SALTWATER, and rope reed carries
-- BIOME_SWAMP_TEMPERATE_SALTWATER).
-- PARAMS: crop (plant raw id). Prints one JSON object.
local SEASONS = {'SPRING', 'SUMMER', 'AUTUMN', 'WINTER'}
local ok, err = pcall(function()
  local raws = df.global.world.raws.plants.all
  local found = nil
  local index = nil
  for i, p in ipairs(raws) do
    if tostring(p.id) == PARAMS.crop then
      found = p
      -- ipairs on a DFHack vector is 0-based (verified live
      -- 2026-11-27: ipairs gives 172 for MUSHROOM_HELMET_PLUMP,
      -- the same as raws[172]; raws[171] is WALNUT). Do NOT
      -- subtract 1: `index = i - 1` wrote the previous plant
      -- into the plot — plump helmet became WALNUT, a tree that
      -- can never be farm-planted, which is why autumn/winter
      -- produced 0 PlantSeeds jobs and summer fetched the wrong
      -- seeds (the stored crop was one plant earlier than the
      -- one set).
      index = i
      break
    end
  end
  if found == nil then
    result = {ok = false, crop = PARAMS.crop,
      error = 'no plant raw ' .. tostring(PARAMS.crop)}
    return
  end
  local seasons = dfh_arr()
  local biomes = dfh_arr()
  for k, v in pairs(found.flags) do
    if v then
      local name = tostring(k)
      for _, s in ipairs(SEASONS) do
        if name == s then seasons[#seasons+1] = name end
      end
      if string.sub(name, 1, 6) == 'BIOME_' then
        biomes[#biomes+1] = name
      end
    end
  end
  local cur = df.global.cur_season
  result = {ok = true, crop = PARAMS.crop, index = index,
    depth_min = found.underground_depth_min,
    depth_max = found.underground_depth_max,
    growdur = found.growdur,
    seasons = seasons, biome_flags = biomes,
    cur_season = cur,
    cur_season_name = SEASONS[cur + 1]}
end)
if not ok then
  result = {ok = false, crop = PARAMS.crop, error = tostring(err)}
end
dfh_print(result)
