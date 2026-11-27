-- wealth.lua — fortress value for the scoring system (GOAL.md item 15).
-- There is NO direct wealth read in DFHack 0.47.05-r8: df.global.ui has
-- no `wealth` field and dfhack.economy is nil (verified live 2026-11-27).
-- So fortress value is computed as the sum of dfhack.items.getValue
-- over the fort's own items. The definition, verified live:
--   * iterate df.global.world.items.other.IN_PLAY (the items in play,
--     the same list stocks.lua uses — NOT world.items.all, which also
--     holds wild items and abstract world artifacts);
--   * EXCLUDE trader-held goods (a visiting caravan's drink/food/wood
--     sits in merchant-held barrels and wagons but belongs to the
--     merchants, not the fort — the same walk stocks.lua uses, verified
--     live 2026-11-26);
--   * EXCLUDE items lying on the ground (flags.on_ground) — wild
--     stones, plants, and remains scattered across the map;
--   * EXCLUDE abstract world artifacts (pos -30000, flagged artifact,
--     with no in_inventory / in_building / in_job / owned flag) — these
--     are worldgen artifacts in abstract storage, not fort property.
--   * split foreign (imported / embark goods) from non-foreign
--     (created in the fort): `fortress_value` is the total, the number
--     the score's wealth dimension uses; `created_value` is the
--     non-foreign subset, reported for transparency.
-- Verified live 2026-11-27 on Erushtathtat: clean base 125-04-01
-- fortress value 5418 (183 items, created 5 = five 1-value seeds);
-- run-end 125-04-02 fortress value 5410 (183 items, created 5).
-- The in-game z-screen "created wealth" is NOT this number (it
-- excludes imports and counts buildings/architecture, which are not
-- items) — the scoring doc says so explicitly. Do NOT present this
-- as the z-screen figure.
-- Prints one JSON object: {"ok": true, "section": "wealth", ...}
local ok, err = pcall(function()
  local function is_trader_held(it)
    local cont = dfhack.items.getContainer(it)
    local holder = nil
    if cont ~= nil then
      holder = dfhack.items.getHolderUnit(cont)
    end
    if holder == nil then
      holder = dfhack.items.getHolderUnit(it)
    end
    if holder ~= nil and not dfhack.units.isCitizen(holder) then
      return true
    end
    local hb = dfhack.items.getHolderBuilding(it)
    if hb == nil and cont ~= nil then
      hb = dfhack.items.getHolderBuilding(cont)
    end
    if hb ~= nil and hb:getType() == df.building_type.Wagon then
      return true
    end
    return false
  end
  -- Worldgen artifacts sit in abstract storage (pos -30000) with no
  -- location flag. A fort-made artifact is in a building, a stockpile
  -- (a real map position), or a dwarf's inventory, so it is kept.
  local function is_abstract_artifact(it)
    if it.pos.x ~= -30000 then return false end
    local f = it.flags
    return f.artifact and not f.in_inventory and not f.in_building
      and not f.in_job and not f.owned
  end
  local fortress_value, created_value = 0, 0
  local item_count, created_count = 0, 0
  local excluded_trader, excluded_ground = 0, 0
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    if is_trader_held(it) then
      excluded_trader = excluded_trader + 1
    else
      local f = it.flags
      if f.on_ground then
        excluded_ground = excluded_ground + 1
      elseif is_abstract_artifact(it) then
        -- Not fort property; do not count it at all.
      else
        local v_ok, v = pcall(dfhack.items.getValue, it)
        if v_ok and v ~= nil then
          fortress_value = fortress_value + v
          item_count = item_count + 1
          if not f.foreign then
            created_value = created_value + v
            created_count = created_count + 1
          end
        end
      end
    end
  end
  result = {
    ok = true, section = 'wealth',
    wealth = {
      fortress_value = fortress_value,
      created_value = created_value,
      imported_value = fortress_value - created_value,
      item_count = item_count,
      created_count = created_count,
      excluded_trader = excluded_trader,
      excluded_ground = excluded_ground,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'wealth', error = tostring(err)}
end
dfh_print(result)
