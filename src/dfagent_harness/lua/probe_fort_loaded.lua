-- probe_fort_loaded.lua: verify a fort loaded after an embark.
-- Counts citizens, buildings (incl. the wagon), drink/food/wood
-- units in play, and reads the date and pause state. Prints one JSON
-- object. ok is false when no fort is loaded (wrong screen / no units).
local ok, err = pcall(function()
  local vs = dfhack.gui.getCurViewscreen()
  local s = tostring(vs)
  if not s:find("dwarfmodest") then
    result = {ok = false, screen = s,
              error = "not in fortress mode (viewscreen_dwarfmodest)"}
    return
  end
  local n_cit, n_units = 0, 0
  for _, u in ipairs(df.global.world.units.all) do
    n_units = n_units + 1
    if dfhack.units.isCitizen(u) then n_cit = n_cit + 1 end
  end
  local n_bld, wagon = 0, 0
  for _, b in ipairs(df.global.world.buildings.all) do
    n_bld = n_bld + 1
    if b:getType() == df.building_type.Wagon then wagon = wagon + 1 end
  end
  local drink, food, wood, barrel = 0, 0, 0, 0
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    local ty = it:getType()
    if ty == df.item_type.DRINK then drink = drink + it:getStackSize()
    elseif ty == df.item_type.FOOD then food = food + it:getStackSize()
    elseif ty == df.item_type.WOOD then wood = wood + it:getStackSize()
    elseif ty == df.item_type.BARREL then barrel = barrel + 1 end
  end
  result = {
    ok = n_cit > 0 and wagon >= 1,
    screen = "viewscreen_dwarfmodest",
    citizens = n_cit,
    units_all = n_units,
    buildings = n_bld,
    wagon = wagon,
    drink_units = drink,
    food_units = food,
    wood = wood,
    barrels = barrel,
    year = df.global.cur_year,
    season = df.global.cur_season,
    year_tick = df.global.cur_year_tick,
    paused = df.global.pause_state,
  }
  if n_cit <= 0 then result.error = "no citizens" end
  if wagon < 1 then result.error = "no wagon" end
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
