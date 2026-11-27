-- probe_dig_state.lua — read the dig designation bits, the process_dig
-- flag, and the dig job count for a tile. PARAMS: x, y, z.
local ok, err = pcall(function()
  local x, y, z = PARAMS.x, PARAMS.y, PARAMS.z
  local b = dfhack.maps.getTileBlock(x, y, z)
  local des = b.designation[x % 16][y % 16]
  local tt = b.tiletype[x % 16][y % 16]
  local out = {
    ok = true,
    designation = {dig = des.dig, smooth = des.smooth,
      hidden = des.hidden, flow_size = des.flow_size},
    tiletype = df.tiletype.attrs[tt].shape,
    tiletype_name = tostring(tt),
    process_dig = df.global.process_dig,
    process_jobs = df.global.process_jobs,
    job_next_id = df.global.job_next_id,
    n_jobs = 0,
    dig_jobs = {},
  }
  -- world.jobs.list is a LINKED list, not a vector: ipairs over it
  -- yields nothing, so the count below was always 0 (found 2026-11-27
  -- while chasing the farm jobs: the scratch watch scripts used the
  -- same ipairs pattern and read 0 PlantSeeds jobs that were in fact
  -- present). Walk the list like jobs.lua does.
  local node = df.global.world.jobs.list
  local guard = 0
  while node ~= nil and guard < 100000 do
    guard = guard + 1
    local j = node.item
    if j ~= nil then
      out.n_jobs = out.n_jobs + 1
      if j.job_type == df.job_type.Dig then
        out.dig_jobs[#out.dig_jobs+1] = {id = j.id, pos = {j.pos.x, j.pos.y, j.pos.z},
          -- The worker is read via dfhack.job.getWorker (the
          -- established pattern in probe_postings.lua / watch.lua):
          -- the job struct has no usable .worker field.
          worker = dfh_try(function()
            local w = dfhack.job.getWorker(j) return w and w.id or nil
          end, nil)}
      end
    end
    node = node.next
  end
  dfh_print(out)
end)
if not ok then dfh_print({ok = false, error = tostring(err)}) end
