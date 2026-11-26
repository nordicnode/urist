-- act_order.lua — create or remove a manager order.
-- PARAMS: mode ('create'|'remove'), job_type (df.job_type name, create
-- only), amount (create only), order_id (remove only).
-- Create follows DFHack's own workorder.lua pattern: take the next id
-- from world.manager_order_next_id, fill a fresh df.manager_order, insert
-- it into world.manager_orders. Frequency is OneTime; validation is left
-- to the game (the manager noble validates orders on ticks — an order
-- with validated=false will not dispatch until then; see docs/ACTIONS.md).
-- Prints one JSON object.
local ok, err = pcall(function()
  local w = df.global.world
  if PARAMS.mode == 'create' then
    local jt = df.job_type[PARAMS.job_type]
    if jt == nil then error('unknown job type: ' .. tostring(PARAMS.job_type)) end
    if PARAMS.amount == nil or PARAMS.amount < 1 then
      error('amount must be >= 1')
    end
    local id = w.manager_order_next_id
    w.manager_order_next_id = w.manager_order_next_id + 1
    local o = df.manager_order:new()
    o.id = id
    o.job_type = jt
    o.amount_left = PARAMS.amount
    o.amount_total = PARAMS.amount
    o.frequency = df.manager_order.T_frequency.OneTime
    w.manager_orders:insert('#', o)
    result = {ok = true, action = 'order', mode = 'create', id = id,
      job_type = PARAMS.job_type,
      amount_left = o.amount_left, amount_total = o.amount_total}
  elseif PARAMS.mode == 'remove' then
    local idx = nil
    for i = 0, #w.manager_orders - 1 do
      if w.manager_orders[i].id == PARAMS.order_id then idx = i break end
    end
    if idx == nil then
      result = {ok = false, action = 'order', kind = 'precondition',
        error = 'no manager order with id ' .. tostring(PARAMS.order_id)}
      return
    end
    local gone = w.manager_orders[idx]
    local jt = tostring(df.job_type[gone.job_type])
    w.manager_orders:erase(idx)
    gone:delete()
    result = {ok = true, action = 'order', mode = 'remove',
      id = PARAMS.order_id, job_type = jt}
  else
    error('unknown mode: ' .. tostring(PARAMS.mode))
  end
end)
if not ok then
  result = {ok = false, action = 'order', error = tostring(err)}
end
dfh_print(result)
