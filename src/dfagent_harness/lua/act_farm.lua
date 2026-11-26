-- act_farm.lua — place a farm plot via dfhack.buildings.constructBuilding.
-- PARAMS: x, y, z (corner tile), width, height.
-- Verified live 2026-11-26: constructBuilding with type FarmPlot
-- succeeds (building #8 at (80,80,42)); the farmplot struct has no
-- `.type` field, so this helper returns the id and the caller verifies
-- via the observe `buildings` section. The plot needs a soil floor;
-- the game cancels the construction job if the tiles are unsuitable.
-- Prints one JSON object.
local ok, err = pcall(function()
  local b, berr = dfhack.buildings.constructBuilding{
    pos = {x = PARAMS.x, y = PARAMS.y, z = PARAMS.z},
    type = df.building_type.FarmPlot, subtype = -1,
    width = PARAMS.width, height = PARAMS.height,
  }
  if not b then
    result = {ok = false, action = 'build-farm',
      error = tostring(berr or 'constructBuilding failed')}
    return
  end
  result = {ok = true, action = 'build-farm', id = b.id,
    center = dfh_arr({b.centerx, b.centery, b.z}),
    x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
    construction_stage = b.construction_stage}
end)
if not ok then
  result = {ok = false, action = 'build-farm', error = tostring(err)}
end
dfh_print(result)
