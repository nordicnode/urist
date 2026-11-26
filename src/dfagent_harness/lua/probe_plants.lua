-- probe_plants.lua — read-back for designate_chop / designate_gather:
-- for every tree/shrub in a rect, report whether its designation tile is
-- marked (dig=Default). PARAMS: x0,y0,z0,x1,y1,z1, kind ('tree'|'shrub').
-- Classification is by structure, not by the is_shrub flag alone:
-- a tree has tree_info set, a shrub has is_shrub set, and a *sapling*
-- has neither (is_shrub=false, tree_info=nil) — saplings are not
-- choppable and are excluded from both kinds. (Counting saplings as
-- trees set a dig designation on a floor tile, which the game read as
-- a Dig job — found live 2026-11-25.)
-- The des_tile() function below is duplicated in act_plants.lua; keep the
-- two in sync. Prints one JSON object.
local function des_tile(p)
  if p.tree_info == nil then return p.pos.x, p.pos.y, p.pos.z end
  local dx, dy = p.tree_info.dim_x, p.tree_info.dim_y
  local best_x, best_y = nil, nil
  for x = p.pos.x - math.floor(dx / 2), p.pos.x + math.floor(dx / 2) do
    for y = p.pos.y - math.floor(dy / 2), p.pos.y + math.floor(dy / 2) do
      local b = dfhack.maps.getTileBlock(x, y, p.pos.z)
      local tt = b.tiletype[x % 16][y % 16]
      if df.tiletype.attrs[tt].material == df.tiletype_material.TREE then
        if best_x == nil or x > best_x or (x == best_x and y > best_y) then
          best_x, best_y = x, y
        end
      end
    end
  end
  if best_x == nil then return p.pos.x, p.pos.y, p.pos.z end
  return best_x, best_y, p.pos.z
end

local ok, err = pcall(function()
  local plants = dfh_arr()
  local marked = 0
  for _, p in ipairs(df.global.world.plants.all) do
    local is_match = false
    if PARAMS.kind == 'tree' then
      is_match = p.tree_info ~= nil
    elseif PARAMS.kind == 'shrub' then
      is_match = p.flags.is_shrub
    end
    if is_match
      and p.pos.z == PARAMS.z0
      and p.pos.x >= PARAMS.x0 and p.pos.x <= PARAMS.x1
      and p.pos.y >= PARAMS.y0 and p.pos.y <= PARAMS.y1 then
      local dx, dy, dz = des_tile(p)
      local b = dfhack.maps.getTileBlock(dx, dy, dz)
      local is_marked = b.designation[dx % 16][dy % 16].dig
        == df.tile_dig_designation.Default
      if is_marked then marked = marked + 1 end
      plants[#plants+1] = {
        pos = dfh_arr({p.pos.x, p.pos.y, p.pos.z}),
        des = dfh_arr({dx, dy, dz}),
        marked = is_marked,
      }
    end
  end
  result = {ok = true, probe = 'plants', kind = PARAMS.kind,
    total = #plants, marked = marked, plants = plants}
end)
if not ok then
  result = {ok = false, probe = 'plants', error = tostring(err)}
end
dfh_print(result)
