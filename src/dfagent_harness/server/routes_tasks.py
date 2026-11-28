from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json, _req_float, _req_int


def tasks_list(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    from ..daemon import TASK_DEFS
    _json(handler, 200, {"tasks": sorted(TASK_DEFS)})

def task_plan(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # The plan renders the task's REAL steps (daemon.task_plan):
    # a recipe's step list, or the legacy four lines for a
    # single-action task. The route used to fabricate the four
    # lines here for every task, which lied about recipes.
    from ..daemon import task_plan as daemon_task_plan
    name = path[len("/v1/tasks/"):-len("/plan")]
    plan = daemon_task_plan(name)
    if plan is None:
        _error(handler, 404, "NOT_FOUND", f"unknown task {name!r}")
        return
    _json(handler, 200, plan)

def task_run(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "tasks need the daemon")
        return
    name = path[len("/v1/tasks/"):]
    if name.endswith("/cancel"):
        _json(handler, 200, {"ok": False,
                          "detail": "no asynchronous task is "
                                    "running (tasks run "
                                    "synchronously)"})
        return
    try:
        wait = _req_float(body.get("wait", 120), "wait")
        count = _req_int(body.get("count", 1), "count")
        kwargs: dict[str, Any] = {}
        if body.get("building_id") is not None:
            kwargs["building_id"] = _req_int(
                body["building_id"], "building_id")
        if body.get("plant") is not None:
            kwargs["plant"] = str(body["plant"])
        if body.get("season") is not None:
            kwargs["season"] = _req_int(body["season"], "season")
        out = ctx.daemon.run_task(name, wait=wait, count=count,
                              **kwargs)
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    _json(handler, 200, out)