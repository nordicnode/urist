-- act_farm_crop.lua — set a farm plot's crop for one season.
-- Writes plant_id[season] (0-based, 0=spring .. 3=winter; -1 =
-- fallow) on a FarmPlot building and reads it back: the write is
-- only trusted when the read-back matches. The plant index is the
-- index into df.global.world.raws.plants.all (verified live
-- 2026-11-27: MUSHROOM_HELMET_PLUMP is index 172; plant_id is
-- -1 for all four seasons on a new plot). This helper does NO
-- suitability checking — the caller (set_farm_crop) verifies
-- soil/light/season/biome/seeds first; a wrong crop here would
-- silently never plant.
-- PARAMS: building_id, season (0-3), plant_index (int, -1 fallow).
-- Prints one JSON object.
local ok, err = pcall(function()
  local b = df.building.find(PARAMS.building_id)
  if b == nil then
    result = {ok = false, error = 'no building #'
      .. tostring(PARAMS.building_id)}
    return
  end
  if b:getType() ~= df.building_type.FarmPlot then
    result = {ok = false, error = 'building #'
      .. tostring(PARAMS.building_id) .. ' is not a farm plot'}
    return
  end
  local season = PARAMS.season
  if season < 0 or season > 3 then
    result = {ok = false, error = 'bad season ' .. tostring(season)}
    return
  end
  b.plant_id[season] = PARAMS.plant_index
  local ids = dfh_arr()
  for i = 0, 3 do ids[#ids+1] = b.plant_id[i] end
  if ids[season + 1] ~= PARAMS.plant_index then
    result = {ok = false, error = 'plant_id did not stick: season '
      .. tostring(season) .. ' reads ' .. tostring(ids[season + 1])}
    return
  end
  result = {ok = true, action = 'set-farm-crop',
    building_id = PARAMS.building_id, plant_id = ids}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
