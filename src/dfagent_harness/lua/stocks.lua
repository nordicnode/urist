-- stocks.lua — fortress stocks (IN_PLAY items) + full item-type table.
-- Prints one JSON object with both "stocks" and "items" sections.
--
-- Trader goods are EXCLUDED: a visiting caravan's drink/food/wood
-- sits in merchant-held barrels and wagons but belongs to the
-- merchants, not the fort. Verified live 2026-11-26: raw counts read
-- drink 50u / food 211u / wood 15u while the fort's true stocks were
-- drink 0u / food 6u / wood 3u (all 50 drink and 205 food units were
-- in barrels held by merchant units 15390/15393). An item is
-- trader-held when its container (or itself) is held by a
-- non-citizen unit, or sits in a Wagon building. Items inside a
-- container report pos -30000, so position cannot tell them apart —
-- the container/holder walk is the only reliable test. (The
-- `category_stacks` counts below stay raw game-category counts.)
local ok, err = pcall(function()
  local by_type = {}
  local total_stacks, total_units = 0, 0
  local mat_breakdown = {}
  local empty_barrels = 0
  -- Empty barrels (for brewing): a BARREL item with no contained
  -- items. Total barrels is NOT the brewing check — the fort had 15
  -- barrels with only 3 empty (2026-11-27), so a brew x5 against
  -- the total would queue 2 jobs that can never run. getContainedItems
  -- is verified live in this DFHack (r8).
  local function is_empty_barrel(it)
    local ok, cont = pcall(dfhack.items.getContainedItems, it)
    return ok and cont ~= nil and #cont == 0
  end
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
  local function plant_is_brewable(it)
    -- A PLANT item is brewable iff its plant raw defines a DRINK
    -- material (verified live 2026-11-27: plump helmet, pig tail,
    -- cave wheat and sweet pod carry DRINK; quarry bush and dimple
    -- cup do not). The item's material index IS the plant raw index
    -- (a plump helmet PLANT item reads mat_index 172). The old
    -- Python rule matched the material token PLANT:...:DRINK,
    -- which is what brewed DRINK items carry — it counted the
    -- booze, never the plants (external review C3). The flag is
    -- computed here, where the raw is, so the Python side never
    -- has to guess brewability from a token again.
    local idx = dfh_try(function() return it:getMaterialIndex() end,
                        nil)
    if idx == nil then return false end
    return dfh_try(function()
      local raw = df.global.world.raws.plants.all[idx]
      if raw == nil then return false end
      for _, m in ipairs(raw.material) do
        if m.id == "DRINK" then return true end
      end
      return false
    end, false)
  end
  local function add_mat(itype, it)
    local decoded = dfh_try(function()
      return dfhack.matinfo.decode(it:getMaterial(), it:getMaterialIndex())
    end, nil)
    if decoded == nil then return end
    local mi = dfh_try(function()
      return dfhack.matinfo.getToken(decoded)
    end, tostring(decoded))
    if mi then
      local key = tostring(df.item_type[itype]) .. '|' .. mi
      local e = mat_breakdown[key]
      if e == nil then
        e = {units = 0}
        if itype == df.item_type.PLANT then
          e.brewable = plant_is_brewable(it)
        end
        mat_breakdown[key] = e
      end
      e.units = e.units + it:getStackSize()
    end
  end
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    if is_trader_held(it) then
      goto continue
    end
    local t = it:getType()
    local qty = it:getStackSize()
    if t == df.item_type.BARREL and is_empty_barrel(it) then
      empty_barrels = empty_barrels + 1
    end
    local e = by_type[t]
    if not e then e = {stacks = 0, units = 0}; by_type[t] = e end
    e.stacks = e.stacks + 1
    e.units = e.units + qty
    total_stacks = total_stacks + 1
    total_units = total_units + qty
    if t == df.item_type.DRINK or t == df.item_type.FOOD
      or t == df.item_type.MEAT or t == df.item_type.FISH
      or t == df.item_type.PLANT or t == df.item_type.SEEDS
      or t == df.item_type.BAR or t == df.item_type.WOOD
      or t == df.item_type.CLOTH or t == df.item_type.THREAD then
      add_mat(t, it)
    end
    ::continue::
  end
  local function get(t)
    local e = by_type[t]
    if e then return e end
    return {stacks = 0, units = 0}
  end
  local drink = get(df.item_type.DRINK)
  local food_units = get(df.item_type.MEAT).units
    + get(df.item_type.FISH).units + get(df.item_type.FISH_RAW).units
    + get(df.item_type.PLANT).units + get(df.item_type.CHEESE).units
    + get(df.item_type.EGG).units
  local food_stacks = get(df.item_type.MEAT).stacks
    + get(df.item_type.FISH).stacks + get(df.item_type.FISH_RAW).stacks
    + get(df.item_type.PLANT).stacks + get(df.item_type.CHEESE).stacks
    + get(df.item_type.EGG).stacks
  local stone_units = get(df.item_type.BOULDER).units
    + get(df.item_type.ROUGH).units + get(df.item_type.BLOCKS).units
  local items = dfh_arr()
  for t, e in pairs(by_type) do
    items[#items+1] = {
      type = tostring(df.item_type[t]),
      stacks = e.stacks, units = e.units,
    }
  end
  table.sort(items, function(a, b) return a.units > b.units end)
  local mats = dfh_arr()
  for k, v in pairs(mat_breakdown) do
    local sep = string.find(k, '|', 1, true)
    local entry = {
      type = string.sub(k, 1, sep - 1),
      material = string.sub(k, sep + 1),
      units = v.units,
    }
    -- Only PLANT entries carry brewable (true iff the plant raw
    -- defines a DRINK material; see plant_is_brewable above).
    if v.brewable ~= nil then entry.brewable = v.brewable end
    mats[#mats+1] = entry
  end
  table.sort(mats, function(a, b) return a.units > b.units end)
  -- Raw `other` category counts for the headline categories DF players use.
  local cats = {}
  for _, name in ipairs({'ANY_GOOD_FOOD', 'ANY_COOKABLE', 'ANY_EDIBLE_RAW',
                         'ANY_DRINK', 'WOOD', 'BAR', 'CLOTH', 'SEEDS'}) do
    cats[name] = #df.global.world.items.other[df.items_other_id[name]]
  end
  result = {
    ok = true, section = 'stocks',
    stocks = {
      drink_stacks = drink.stacks, drink_units = drink.units,
      food_stacks = food_stacks, food_units = food_units,
      seeds_stacks = get(df.item_type.SEEDS).stacks,
      seeds_units = get(df.item_type.SEEDS).units,
      wood_stacks = get(df.item_type.WOOD).stacks,
      wood_units = get(df.item_type.WOOD).units,
      stone_units = stone_units,
      stone_stacks = get(df.item_type.BOULDER).stacks
        + get(df.item_type.ROUGH).stacks + get(df.item_type.BLOCKS).stacks,
      cloth_units = get(df.item_type.CLOTH).units,
      thread_units = get(df.item_type.THREAD).units,
      metal_bar_units = get(df.item_type.BAR).units,
      metal_bar_stacks = get(df.item_type.BAR).stacks,
      barrels = get(df.item_type.BARREL).stacks,
      empty_barrels = empty_barrels,
      bins = get(df.item_type.BIN).stacks,
      buckets = get(df.item_type.BUCKET).stacks,
      category_stacks = cats,
      by_material = mats,
    },
    items = {
      total_stacks = total_stacks, total_units = total_units,
      by_type = items,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'stocks', error = tostring(err)}
end
dfh_print(result)
