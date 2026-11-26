-- stocks.lua — fortress stocks (IN_PLAY items) + full item-type table.
-- Prints one JSON object with both "stocks" and "items" sections.
local ok, err = pcall(function()
  local by_type = {}
  local total_stacks, total_units = 0, 0
  local mat_breakdown = {}
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
      mat_breakdown[key] = (mat_breakdown[key] or 0) + it:getStackSize()
    end
  end
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    local t = it:getType()
    local qty = it:getStackSize()
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
    mats[#mats+1] = {
      type = string.sub(k, 1, sep - 1),
      material = string.sub(k, sep + 1),
      units = v,
    }
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
