-- equip_pick.lua — diagnostic: move a pick on the ground into the
-- miner's inventory as a Weapon (mode 1), to test whether the game
-- creates a Dig job only when a miner already HOLDS a pick.
-- PARAMS: unit_id. Finds the first pick (weapon subtype 6) on the
-- ground and moves it to the unit.
local ok, err = pcall(function()
  local unit = df.unit.find(PARAMS.unit_id)
  if not unit then error("no unit " .. tostring(PARAMS.unit_id)) end
  local pick = nil
  for _, it in ipairs(df.global.world.items.all) do
    if it:getType() == df.item_type.WEAPON and it:getSubtype() == 6
       and it.flags.on_ground and not it.flags.forbid then
      pick = it
      break
    end
  end
  if not pick then error("no pick on the ground") end
  local moved = dfhack.items.moveToInventory(pick, unit, 1, -1)
  -- use_mode 1 = Weapon (the inv_item_role_type enum is not exposed
  -- in this DFHack build; the modes are Hauled=0, Weapon=1, Worn=2).
  if not moved then error("moveToInventory returned false") end
  -- Verify: is the pick in the miner's inventory now?
  local has = false
  for _, inv in ipairs(unit.inventory) do
    if inv.item.id == pick.id then has = true end
  end
  dfh_print({ok = true, pick_id = pick.id, moved = moved,
             in_inventory = has})
end)
if not ok then dfh_print({ok = false, error = tostring(err)}) end
