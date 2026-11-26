-- act_plants.lua — mark/unmark trees (chop) or shrubs (gather) in a rect.
-- PARAMS: x0,y0,z0,x1,y1,z1, kind ('tree'|'shrub'), mark (bool).
--
-- Mechanism (DFHack 0.47.05-r8, library/modules/Designations.cpp):
-- a plant is designated by setting dig=Default on its *designation tile*
-- and block.flags.designated=true. For shrubs the designation tile is the
-- plant's own tile; for trees it is the SE-most trunk tile of the tree's
-- footprint (DFHack walks SE from the footprint centre while the tile is
-- trunk; the SE-most trunk tile is the same tile for single-trunk trees
-- and a valid trunk tile for multi-trunk trees). Trunk tiles are found by
-- tiletype material TREE at the tree's z-level. Unmarking also removes any
-- FellTree/GatherPlants job at the designation tile (same as DFHack's
-- unmarkPlant), so no dwarf walks out to a tree that is no longer marked.
--
-- Classification is by structure: a tree has tree_info set, a shrub has
-- is_shrub set, and a *sapling* has neither (is_shrub=false,
-- tree_info=nil) — saplings are excluded from both kinds. (Counting a
-- sapling as a tree set a dig designation on a floor tile, which the
-- game read as a Dig job — found live 2026-11-25.)
--
-- The des_tile() function below is duplicated in probe_plants.lua; keep
-- the two in sync. Prints one JSON object.
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
  if PARAMS.kind ~= 'tree' and PARAMS.kind ~= 'shrub' then
    error('unknown plant kind: ' .. tostring(PARAMS.kind))
  end
  local changed = dfh_arr()
  local already = dfh_arr()
  local found = 0
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
      found = found + 1
      local dx, dy, dz = des_tile(p)
      local b = dfhack.maps.getTileBlock(dx, dy, dz)
      local d = b.designation[dx % 16][dy % 16]
      local entry = {
        pos = dfh_arr({p.pos.x, p.pos.y, p.pos.z}),
        des = dfh_arr({dx, dy, dz}),
      }
      if PARAMS.mark then
        if d.dig == df.tile_dig_designation.Default then
          already[#already+1] = entry
        else
          d.dig = df.tile_dig_designation.Default
          b.flags.designated = true
          changed[#changed+1] = entry
        end
      else
        if d.dig == df.tile_dig_designation.Default then
          d.dig = df.tile_dig_designation.No
          b.flags.designated = true
          changed[#changed+1] = entry
          -- remove any FellTree/GatherPlants job at the designation tile
          -- (save next first: removeJob mutates the list)
          local node = df.global.world.jobs.list
          while node ~= nil do
            local nxt = node.next
            local job = node.item
            if job ~= nil
              and (job.job_type == df.job_type.FellTree
                or job.job_type == df.job_type.GatherPlants)
              and job.pos.x == dx and job.pos.y == dy and job.pos.z == dz then
              dfhack.job.removeJob(job)
            end
            node = nxt
          end
        else
          already[#already+1] = entry
        end
      end
    end
  end
  if found == 0 then
    result = {ok = false, action = 'plants', kind = 'precondition',
      error = 'no ' .. PARAMS.kind .. 's in area', found = 0}
    return
  end
  result = {ok = true, action = 'plants', kind = PARAMS.kind,
    mark = PARAMS.mark, found = found,
    changed = changed, already = already}
end)
if not ok then
  result = {ok = false, action = 'plants', error = tostring(err)}
end
dfh_print(result)
