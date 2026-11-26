-- probe_jobs_at.lua — read-back for the async half of chop/gather/dig:
-- list jobs of the given types at the given tile positions.
-- PARAMS: tiles (array of [x,y,z]), types (array of df.job_type names).
-- Prints one JSON object.
local ok, err = pcall(function()
  local wanted = {}
  for _, t in ipairs(PARAMS.types) do wanted[t] = true end
  local found = dfh_arr()
  local node = df.global.world.jobs.list
  local guard = 0
  while node ~= nil and guard < 100000 do
    guard = guard + 1
    local job = node.item
    if job ~= nil then
      local tname = tostring(df.job_type[job.job_type])
      if wanted[tname] then
        for _, tp in ipairs(PARAMS.tiles) do
          if job.pos.x == tp[1] and job.pos.y == tp[2] and job.pos.z == tp[3] then
            found[#found+1] = {
              id = job.id,
              type = tname,
              pos = dfh_arr({job.pos.x, job.pos.y, job.pos.z}),
            }
          end
        end
      end
    end
    node = node.next
  end
  result = {ok = true, probe = 'jobs_at', jobs = found, count = #found}
end)
if not ok then
  result = {ok = false, probe = 'jobs_at', error = tostring(err)}
end
dfh_print(result)
