-- act_job.lua — queue a job on a workshop via Lua (phase 4).
-- PARAMS: building_id (int), job_type (int, df.job_type value),
-- reaction_name (string or nil — set for CustomReaction jobs),
-- count (int, default 1 — how many copies to queue).
-- Workshop item jobs (beds, barrels, brewing) are REACTIONS in
-- 0.47.05, not job types: use job_type 211 (CustomReaction) with
-- reaction_name e.g. 'BREW_DRINK_FROM_PLANT' or 'MAKE WOODEN BED'.
-- Plain jobs (e.g. PrepareMeal=115, MakeBarrel=127) take no
-- reaction_name. Job items are built from the reaction's reagents
-- (same fields as df.job_item), which is what the game does when the
-- q-menu creates the job — a bare job with no job_items is never
-- claimed. The job is linked into world.jobs AND inserted into the
-- building's jobs list (linkIntoWorld alone never dispatches).
-- Prints one JSON object.
local ok, err = pcall(function()
  local bid = PARAMS.building_id
  local b = df.building.find(bid)
  if b == nil then error('no building #' .. tostring(bid)) end
  if b.jobs == nil then error('building #' .. tostring(bid) .. ' takes no jobs') end
  local jt = PARAMS.job_type
  if type(jt) ~= 'number' then error('job_type must be an int (df.job_type value)') end
  local count = PARAMS.count or 1
  if count < 1 then error('count must be >= 1') end
  local reaction = nil
  if PARAMS.reaction_name ~= nil then
    reaction = nil
    for i = 0, 3000 do
      local r = df.reaction.find(i)
      if r == nil then break end
      if r.code == PARAMS.reaction_name then reaction = r break end
    end
    if reaction == nil then error('unknown reaction: ' .. tostring(PARAMS.reaction_name)) end
  end
  local made = {}
  for n = 1, count do
    local job = df.job:new()
    job.job_type = jt
    job.pos.x = b.centerx
    job.pos.y = b.centery
    job.pos.z = b.z
    if reaction ~= nil then
      job.reaction_name = reaction.code
      for ri, rg in ipairs(reaction.reagents) do
        local ji = df.job_item:new()
        ji.item_type = rg.item_type
        ji.item_subtype = rg.item_subtype
        ji.mat_type = rg.mat_type
        ji.mat_index = rg.mat_index
        ji.quantity = rg.quantity
        ji.has_material_reaction_product = rg.has_material_reaction_product
        ji.reaction_class = rg.reaction_class
        ji.metal_ore = rg.metal_ore
        ji.min_dimension = rg.min_dimension
        ji.has_tool_use = rg.has_tool_use
        ji.reaction_id = reaction.index
        ji.reagent_index = ri - 1
        ji.flags1:assign(rg.flags1)
        ji.flags2:assign(rg.flags2)
        ji.flags3:assign(rg.flags3)
        job.job_items:insert('#', ji)
      end
    end
    dfhack.job.linkIntoWorld(job)
    b.jobs:insert('#', job)
    table.insert(made, job.id)
  end
  result = {ok = true, action = 'queue-job', building_id = bid,
    job_type = jt, reaction_name = PARAMS.reaction_name,
    job_ids = dfh_arr(made), count = count}
end)
if not ok then
  result = {ok = false, action = 'queue-job', error = tostring(err)}
end
dfh_print(result)
