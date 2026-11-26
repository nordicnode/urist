-- jobs.lua — queued jobs (linked-list walk) + manager orders.
-- Manager-order / job struct fields are dumped generically (dfh_dump):
-- no live instance existed on a fresh fort to probe field names against,
-- so named fields are read best-effort and the raw scalar dump is kept.
-- Prints one JSON object: {"ok": true, "section": "jobs", ...}
local ok, err = pcall(function()
  local list = dfh_arr()
  local by_type = {}
  local node = df.global.world.jobs.list
  local guard = 0
  while node ~= nil and guard < 100000 do
    guard = guard + 1
    local job = node.item
    if job ~= nil then
      local tname = tostring(df.job_type[job.job_type])
      by_type[tname] = (by_type[tname] or 0) + 1
      list[#list+1] = {
        id = job.id,
        type = tname,
        pos = dfh_arr({job.pos.x, job.pos.y, job.pos.z}),
        suspend = dfh_try(function() return job.flags.suspend end, nil),
        repeat_ = dfh_try(function() return job.flags.repeat_ end, nil),
      }
    end
    node = node.next
  end
  local counts = dfh_arr()
  for k, v in pairs(by_type) do counts[#counts+1] = {type = k, count = v} end
  table.sort(counts, function(a, b) return a.count > b.count end)
  local orders = dfh_arr()
  for _, o in ipairs(df.global.world.manager_orders) do
    local d = dfh_dump(o)
    d.job_type_name = dfh_try(function()
      return tostring(df.job_type[o.job_type])
    end, nil)
    orders[#orders+1] = d
  end
  result = {
    ok = true, section = 'jobs',
    jobs = {
      list = list,
      count = #list,
      counts_by_type = counts,
      manager_orders = orders,
      manager_order_count = #orders,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'jobs', error = tostring(err)}
end
dfh_print(result)
