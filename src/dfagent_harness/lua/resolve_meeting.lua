-- resolve_meeting.lua — end a topicmeeting (liaison meeting peek view)
-- programmatically. Proven live 2026-11-27 on the scratch fort
-- (region5, tick 222291): the topicmeeting cannot be dismissed with
-- dfhack.screen.dismiss — the game re-creates it every tick while the
-- meeting's dipscript is mid-conversation. The programmatic route:
-- write meeting.cur_step to the LAST step index (the bye textviewer
-- step, whose next_step_idx is -1 = script end), then dismiss the
-- topicmeeting child + parent meetingst. The next tick presents the
-- bye textviewer (dismissable by the proven textviewer route), the
-- game sets cur_step to -1 (its own done marker), the liaison leaves,
-- and the clock runs. No keypress is used anywhere in this route.
--
-- Refuses (ok=false, nothing written) unless the last step is a
-- textviewer step (has a filename) whose next_step_idx is -1 — the
-- route only applies to a script that ends in a farewell text.
local result = {ok = true}
local ok, err = pcall(function()
  local cur = dfhack.gui.getCurViewscreen()
  local stype = tostring(cur)
  if not string.find(stype, "viewscreen_topicmeetingst") then
    result = {ok = false,
              reason = "current screen is not a topicmeeting: " .. stype}
    return
  end
  local meeting = cur.meeting
  if meeting == nil then
    result = {ok = false, reason = "topicmeeting has no meeting field"}
    return
  end
  local ds = meeting.dipscript
  if ds == nil then
    result = {ok = false, reason = "meeting has no dipscript"}
    return
  end
  local steps = ds.script_steps
  local n = #steps
  if n == 0 then
    result = {ok = false, reason = "dipscript has no steps"}
    return
  end
  local last = steps[n - 1]
  local next_idx = last.next_step_idx
  local fname = nil
  pcall(function() fname = last.filename end)
  result.before = {
    cur_step = meeting.cur_step,
    n_steps = n,
    last_step = n - 1,
    last_next_step_idx = next_idx,
    last_filename = fname,
  }
  if next_idx ~= -1 or fname == nil or fname == "" then
    result.ok = false
    result.reason = "last dipscript step is not a farewell textviewer "
      .. "(next_step_idx=" .. tostring(next_idx)
      .. ", filename=" .. tostring(fname) .. "); refusing to jump"
    return
  end
  -- Jump the conversation to its farewell step. The discussion
  -- steps' state effects (topic list built, history recorded) have
  -- already happened by the time the peek view is showing; only the
  -- discussion display and the farewell remain.
  meeting.cur_step = n - 1
  result.write_readback = meeting.cur_step
  local parent = cur.parent
  local ok1 = pcall(dfhack.screen.dismiss, cur)
  local ok2 = pcall(dfhack.screen.dismiss, parent)
  result.dismiss = {
    child_ok = ok1,
    child_dismissed = dfhack.screen.isDismissed(cur),
    parent_ok = ok2,
    parent_dismissed = dfhack.screen.isDismissed(parent),
  }
  result.after = {cur_step = meeting.cur_step}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
