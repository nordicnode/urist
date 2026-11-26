local out = {weapons = {}, miner = {}}
for _, it in ipairs(df.global.world.items.all) do
  if it:getType() == df.item_type.WEAPON then
    local pos = it.pos
    out.weapons[#out.weapons+1] = {id = it.id, subtype = it:getSubtype(), x = pos.x, y = pos.y, z = pos.z,
      forbid = it.flags.forbid, in_building = it.flags.in_building, in_inventory = it.flags.in_inventory, on_ground = it.flags.on_ground}
  end
end
for _, u in ipairs(df.global.world.units.active) do
  if u.id == 5407 then
    for _, inv in ipairs(u.inventory) do
      local it = inv.item
      out.miner[#out.miner+1] = {type = it:getType(), subtype = it:getSubtype(), mode = inv.mode}
    end
    out.miner_has_job = u.job ~= nil
    out.miner_pos = {u.pos.x, u.pos.y, u.pos.z}
  end
end
dfh_print(out)
