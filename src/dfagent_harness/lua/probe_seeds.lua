-- probe_seeds.lua — seeds on hand, per crop (plant raw id).
-- Counts df.global.world.items.other.SEEDS by material token
-- (PLANT:<RAW_ID>:SEED) and splits each crop's count into
-- in-play seeds and seeds still in the embark wagon: at a fresh
-- embark every seed sits in a seed bag inside the wagon (verified
-- live 2026-11-27: 30 seed items, 5 each of 6 dwarven crops, all
-- in a container whose holder building is a Wagon), so the
-- headline stocks read of seeds_stacks 0 is wrong for planting
-- purposes. Wagon seeds ARE the fort's — they become plantable
-- once hauled out (deconstruct the wagon / build a stockpile) —
-- so the split is reported, not hidden. Trader-held seeds (held
-- by a non-citizen unit, or in a container held by one) are
-- excluded: a caravan's seeds are not the fort's.
-- Prints one JSON object.
local ok, err = pcall(function()
  local by_plant = {}
  local total_stacks = 0
  for _, it in ipairs(df.global.world.items.other.SEEDS) do
    local cont = dfhack.items.getContainer(it)
    local holder = dfhack.items.getHolderUnit(it)
    if holder == nil and cont ~= nil then
      holder = dfhack.items.getHolderUnit(cont)
    end
    if holder ~= nil and not dfhack.units.isCitizen(holder) then
      goto continue
    end
    local decoded = dfhack.matinfo.decode(it:getMaterial(),
                                           it:getMaterialIndex())
    local token = dfhack.matinfo.getToken(decoded)
    -- token is PLANT:<RAW_ID>:SEED; the raw id is the middle part.
    local raw = string.match(token, '^PLANT:([^:]+):SEED$')
    if raw == nil then goto continue end
    local in_wagon = false
    local hb = dfhack.items.getHolderBuilding(it)
    if hb == nil and cont ~= nil then
      hb = dfhack.items.getHolderBuilding(cont)
    end
    if hb ~= nil and hb:getType() == df.building_type.Wagon then
      in_wagon = true
    end
    local e = by_plant[raw]
    if e == nil then
      e = {units = 0, in_wagon_units = 0, stacks = 0}
      by_plant[raw] = e
    end
    e.units = e.units + it:getStackSize()
    e.stacks = e.stacks + 1
    if in_wagon then e.in_wagon_units = e.in_wagon_units
      + it:getStackSize() end
    total_stacks = total_stacks + 1
    ::continue::
  end
  result = {ok = true, by_plant = by_plant,
            total_stacks = total_stacks}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
