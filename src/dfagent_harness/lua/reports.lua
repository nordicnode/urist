-- reports.lua — recent announcements + combat reports.
-- Struct fields are dumped generically (dfh_dump): both lists are empty
-- on a fresh fort, so no field names could be probed live; named fields
-- (text/year/year_tick/pos) are read best-effort and the raw scalar dump
-- is kept alongside so nothing is lost.
-- Prints one JSON object: {"ok": true, "section": "reports", ...}
local ok, err = pcall(function()
  local function take_tail(vec, n)
    local out = dfh_arr()
    local start = math.max(1, #vec - n + 1)
    for i = start, #vec do out[#out+1] = vec[i] end
    return out
  end
  local function entry(r)
    local d = dfh_dump(r)
    d.text = dfh_try(function() return r.text end, d.text)
    d.year = dfh_try(function() return r.year end, d.year)
    d.year_tick = dfh_try(function() return r.year_tick end, d.year_tick)
    local px = dfh_try(function() return r.pos.x end, nil)
    if px ~= nil then
      d.pos = dfh_arr({px,
        dfh_try(function() return r.pos.y end, 0),
        dfh_try(function() return r.pos.z end, 0)})
    end
    return d
  end
  local anns = dfh_arr()
  for _, a in ipairs(take_tail(df.global.world.status.announcements, 20)) do
    anns[#anns+1] = entry(a)
  end
  local reps = dfh_arr()
  for _, r in ipairs(take_tail(df.global.world.status.reports, 20)) do
    reps[#reps+1] = entry(r)
  end
  result = {
    ok = true, section = 'reports',
    reports = {
      announcements = anns,
      announcement_count = #df.global.world.status.announcements,
      reports = reps,
      report_count = #df.global.world.status.reports,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'reports', error = tostring(err)}
end
dfh_print(result)
