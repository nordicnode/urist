-- watch.lua — DFH eventful watcher (phase 3).
--
-- Registers DFHack eventful handlers that append one JSON object per
-- line to the DFH event log (absolute path substituted by the Python
-- installer: __DFH_EVENT_LOG__). The daemon drains that file; see
-- docs/EVENTS.md and src/dfagent_harness/events.py.
--
-- Installed by running this file (prepended with lua/json.lua) as a
-- one-shot `RunCommand("lua", code)` — no script-path setup needed:
-- the handlers live in the eventful Lua module state for the life of
-- the DF process. Re-running is idempotent (same handler key,
-- baseline re-taken).
--
-- Verified live 2026-11-26 on DFHack 0.47.05-r8 (probe `dfh-probe`):
--   * `require('plugins.eventful')`, `enableEvent`, and the `onX`
--     handler tables work in fortress mode.
--   * JOB_COMPLETED fires on real completions (14 Eat/Drink2
--     completions in ~18k ticks); UNIT_DEATH fires (17 in one run,
--     wildlife); REPORT and UNIT_NEW_ACTIVE fire.
--   * Enabling REPORT / UNIT_NEW_ACTIVE REPLAYS the backlog: every
--     existing report index and every active unit fires once, spread
--     over frames even while paused. Hence the baseline below: events
--     at or below the install-time counts/ids are suppressed here, so
--     the daemon never sees the replay.
--   * Handler args are DFHack userdata/numbers, not plain tables:
--     JOB_COMPLETED gets the job struct (read .id/.job_type via pcall),
--     REPORT gets a report index (number), UNIT_NEW_ACTIVE and
--     UNIT_DEATH get the unit ID (a number, not the struct).
--   * A dead unit is already gone from world.units.all, so the
--     watcher cannot resolve a death's name — it emits the id only
--     and the daemon resolves it against its last snapshot.
--     A newly-active unit IS in the active list at fire time, so
--     hostility/name resolve in the watcher.
--
-- World reload: eventful clears its C++ listeners on unload. This
-- script hooks dfhack.onStateChange.dfh_watch to re-enable + re-baseline
-- on SC_WORLD_LOADED. That path is designed, not live-tested (no world
-- reload was performed in phase 3); the daemon also reinstalls the
-- watcher on start, which is the tested route.

local DFH_EVENT_LOG = '__DFH_EVENT_LOG__'

-- Baseline, taken BEFORE enableEvent so the replay is suppressible.
local baseline_report_count = 0
local baseline_units = {}
local function take_baseline()
  baseline_report_count = dfh_try(function()
    return #df.global.world.status.reports
  end, 0) or 0
  baseline_units = {}
  for _, u in ipairs(df.global.world.units.active) do
    baseline_units[u.id] = true
  end
end

local function emit(obj)
  local ok, err = pcall(function()
    obj.tick = df.global.cur_year_tick
    obj.year = df.global.cur_year
    local fh = io.open(DFH_EVENT_LOG, 'a')
    if fh then
      fh:write(dfh_encode(obj) .. '\n')
      fh:close()
    end
  end)
  if not ok then
    -- Never let a logging failure break the game tick. The failure is
    -- visible in stderr.log via DFHack's own print path.
    print('dfh-watch emit error: ' .. tostring(err))
  end
end

local function resolve_report(idx)
  -- Try the raw index and index-1 (0-based vector vs 1-based arg).
  for _, i in ipairs({idx, idx - 1}) do
    local r = dfh_try(function()
      return df.global.world.status.reports[i]
    end, nil)
    if r ~= nil then
      local text = dfh_try(function() return r.text end, nil)
      return {
        index = idx,
        text = text,
        year = dfh_try(function() return r.year end, nil),
        time = dfh_try(function() return r.time end, nil),
        announcement = dfh_try(function() return r.announcement end, nil),
      }
    end
  end
  return {index = idx}
end

local function install()
  take_baseline()
  local ev = require('plugins.eventful')
  ev.enableEvent(ev.eventType.JOB_COMPLETED, 1)
  ev.onJobCompleted['dfh-watch'] = function(job)
    emit({
      kind = 'JOB_COMPLETED',
      job_id = dfh_try(function() return job.id end, nil),
      job_type = dfh_try(function()
        return tostring(df.job_type[job.job_type])
      end, nil),
      worker_id = dfh_try(function()
        return dfhack.job.getWorker(job).id
      end, nil),
      pos = dfh_try(function()
        return dfh_arr({job.pos.x, job.pos.y, job.pos.z})
      end, nil),
    })
  end
  ev.enableEvent(ev.eventType.UNIT_DEATH, 1)
  ev.onUnitDeath['dfh-watch'] = function(unit_id)
    -- eventful passes the unit ID (a number), not the struct — and a
    -- dead unit is already gone from world.units.all, so its name
    -- cannot be resolved here. The daemon resolves the id against its
    -- last snapshot (the unit was alive then). Emit the id only.
    emit({kind = 'UNIT_DEATH', unit_id = unit_id})
  end
  ev.enableEvent(ev.eventType.REPORT, 1)
  ev.onReport['dfh-watch'] = function(idx)
    if type(idx) == 'number' and idx <= baseline_report_count then
      return -- replay of a pre-install report; suppress
    end
    local rec = resolve_report(idx)
    rec.kind = 'REPORT'
    emit(rec)
  end
  ev.enableEvent(ev.eventType.INVASION, 1)
  ev.onInvasion['dfh-watch'] = function(...)
    -- Signature unsettled (no live invasion in phase 3): record raw args.
    local args = dfh_arr()
    for i = 1, select('#', ...) do
      local v = select(i, ...)
      local t = type(v)
      if t == 'number' or t == 'string' or t == 'boolean' then
        args[#args + 1] = v
      elseif t == 'userdata' or t == 'table' then
        args[#args + 1] = dfh_try(function() return v.id end, tostring(v))
      else
        args[#args + 1] = t
      end
    end
    emit({kind = 'INVASION', args = args})
  end
  ev.enableEvent(ev.eventType.UNIT_NEW_ACTIVE, 1)
  ev.onUnitNewActive['dfh-watch'] = function(unit_id)
    -- eventful passes the unit ID (a number). The unit IS in the
    -- active list at fire time, so hostility/name resolve here.
    if type(unit_id) == 'number' and baseline_units[unit_id] then
      return -- replay of a unit active before install; suppress
    end
    local found = nil
    if type(unit_id) == 'number' then
      for _, u in ipairs(df.global.world.units.active) do
        if u.id == unit_id then found = u break end
      end
    end
    emit({
      kind = 'UNIT_NEW_ACTIVE',
      unit_id = unit_id,
      hostile = found ~= nil and dfh_try(function()
        return dfhack.units.isOpposedToLife(found)
          or found.flags1.active_invader
      end, nil) or nil,
      name = found ~= nil and dfh_try(function()
        return dfhack.TranslateName(dfhack.units.getVisibleName(found))
      end, nil) or nil,
      race = found ~= nil and dfh_try(function()
        return dfhack.units.getRaceName(found)
      end, nil) or nil,
      pos = found ~= nil and dfh_try(function()
        return dfh_arr({found.pos.x, found.pos.y, found.pos.z})
      end, nil) or nil,
    })
  end
  print('DFH-WATCH-OK log=' .. DFH_EVENT_LOG
    .. ' baseline_reports=' .. tostring(baseline_report_count))
end

-- Re-install on world load (handlers are cleared on unload). The daemon
-- also reinstalls on start; this is the in-game backstop.
dfhack.onStateChange.dfh_watch = function(state)
  if state == SC_WORLD_LOADED then
    local ok, err = pcall(install)
    if not ok then print('dfh-watch reinstall error: ' .. tostring(err)) end
  end
end

install()
