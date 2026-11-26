-- probe_postings.lua — dump the job postings (world.jobs.postings)
-- and the active jobs list, with types and positions.
local ok, err = pcall(function()
  local out = {ok = true, postings = {}, jobs = {}}
  for i, p in ipairs(df.global.world.jobs.postings) do
    if p.job then
      out.postings[#out.postings+1] = {job_type = tostring(df.job_type[p.job.job_type]),
        pos = {p.job.pos.x, p.job.pos.y, p.job.pos.z},
        dead = p.flags.dead, job_id = p.job.id}
    end
  end
  local node = df.global.world.jobs.list
  local guard = 0
  while node ~= nil and guard < 100000 do
    guard = guard + 1
    local job = node.item
    if job ~= nil then
      out.jobs[#out.jobs+1] = {id = job.id,
        job_type = tostring(df.job_type[job.job_type]),
        pos = {job.pos.x, job.pos.y, job.pos.z},
        worker = (dfhack.job.getWorker(job) or {}).id}
    end
    node = node.next
  end
  dfh_print(out)
end)
if not ok then dfh_print({ok = false, error = tostring(err)}) end
