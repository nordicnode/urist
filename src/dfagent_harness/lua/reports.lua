-- reports.lua — recent announcements + combat reports.
-- Struct fields are dumped generically (dfh_dump); named fields
-- (text/year/time/pos) are read best-effort and the raw scalar dump
-- is kept alongside so nothing is lost. Verified on non-empty data
-- 2026-11-25/26 (build-cancellation and weather announcements): the
-- struct field is `time` (tick within the year), not `year_tick`, and
-- DFHack Lua vectors are 0-based (take_tail used 1-based indexing
-- before the fix and crashed on any non-empty list).
-- Prints one JSON object: {"ok": true, "section": "reports", ...}
local ok, err = pcall(function()
  local function take_tail(vec, n)
    -- DFHack Lua vectors are 0-based: indices 0..#vec-1.
    local out = dfh_arr()
    local start = math.max(0, #vec - n)
    for i = start, #vec - 1 do out[#out+1] = vec[i] end
    return out
  end
  local function entry(r)
    local d = dfh_dump(r)
    d.text = dfh_try(function() return r.text end, d.text)
    d.year = dfh_try(function() return r.year end, d.year)
    -- The struct field is `time` (tick within the year), not `year_tick`.
    d.time = dfh_try(function() return r.time end, d.time)
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
