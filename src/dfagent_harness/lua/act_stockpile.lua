-- act_stockpile.lua — create a stockpile programmatically.
-- The route (verified live 2026-11-26, building #8): dfhack.buildings.
-- constructBuilding with type=Stockpile and abstract=true, then set
-- the category flag on the stockpile's settings, then
-- dfhack.job.checkBuildingsNow() so the game re-checks buildings.
-- NEVER use dfhack.buildings.constructAbstract on a hand-built
-- building: it CRASHED the game live 2026-11-26 (see docs/PLANNER.md).
-- constructBuilding with abstract=true is a different call (one
-- call, no allocInstance) and is the route quickfort uses
-- (scripts/internal/quickfort/place.lua: constructBuilding +
-- stockpiles.import_settings('library/cat_<category>') +
-- dfhack.job.checkBuildingsNow()).
-- The category flag (settings.flags.<category> = true) is set here.
-- The category's sub-vectors (food.plants, food.meat, ...) are left
-- as constructBuilding leaves them (empty). Whether an empty
-- sub-vector blocks hauling is OPEN (2026-11-26): a plump helmet
-- spawned on the ground was not hauled to stockpile #8 in 25 s, and
-- no StoreItemInStockpile job was created, but the spawned item may
-- not have been registered by the game's hauling scan. The
-- definitive test is a NATURALLY occurring loose food item (a
-- gathered plant) — watch whether it is hauled to the stockpile.
-- The r8 stockpiles plugin has no import_settings / library files,
-- so the sub-vectors cannot be populated from a library preset here.
-- PARAMS: x,y,z,width,height,category (one of the settings.flags
-- names: food, wood, stone, refuse, furniture, ...). Prints JSON.
local ok, err = pcall(function()
  local cat = PARAMS.category or 'food'
  local b, err2 = dfhack.buildings.constructBuilding{
    type = df.building_type.Stockpile,
    pos = {x = PARAMS.x, y = PARAMS.y, z = PARAMS.z},
    width = PARAMS.width, height = PARAMS.height,
    abstract = true,
  }
  if not b then
    result = {ok = false, error = tostring(err2)}
    return
  end
  -- Set the category flag so the stockpile accepts that category.
  local s = b.settings
  if s and s.flags and s.flags[cat] ~= nil then
    s.flags[cat] = true
  else
    result = {ok = false, error = 'unknown stockpile category '
      .. tostring(cat), building_id = b.id}
    return
  end
  dfhack.job.checkBuildingsNow()
  result = {ok = true, building_id = b.id,
    category = cat, flag_set = s.flags[cat],
    pos = {b.x1, b.y1, b.z},
    width = b.x2 - b.x1 + 1, height = b.y2 - b.y1 + 1}
end)
if not ok then result = {ok = false, error = tostring(err)} end
dfh_print(result)
