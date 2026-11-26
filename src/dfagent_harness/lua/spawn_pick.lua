-- spawn_pick.lua — diagnostic only: create one iron pick on the
-- ground at the fort (97, 95, 175) to test whether pick availability
-- gates Dig job creation. PARAMS: x, y, z, unit_id (the creator,
-- required — createItem takes a non-nil unit).
local ok, err = pcall(function()
  local mat = dfhack.matinfo.find("INORGANIC:IRON")
  if not mat then error("no INORGANIC:IRON material") end
  local creator = df.unit.find(PARAMS.unit_id)
  if not creator then error("no unit " .. tostring(PARAMS.unit_id)) end
  local item_id = dfhack.items.createItem(
    df.item_type.WEAPON, 6, mat.type, mat.index, creator)
  if not item_id then error("createItem returned nil") end
  -- createItem returns an item ID (a number), not the item object.
  local item = df.item.find(item_id)
  if not item then error("created pick " .. tostring(item_id) .. " not found") end
  item.pos.x = PARAMS.x
  item.pos.y = PARAMS.y
  item.pos.z = PARAMS.z
  item.flags.on_ground = true
  dfh_print({ok = true, id = item.id, pos = {PARAMS.x, PARAMS.y, PARAMS.z}})
end)
if not ok then dfh_print({ok = false, error = tostring(err)}) end
