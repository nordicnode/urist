from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json, _req_int


def goals_list(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "goals need the daemon")
        return
    _json(handler, 200, {"goals": ctx.daemon.journal.list_goals()})

def goal_get(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "goals need the daemon")
        return
    try:
        gid = int(path[len("/v1/goals/"):])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST", "bad goal id")
        return
    goal = ctx.daemon.journal.get_goal(gid)
    if goal is None:
        _error(handler, 404, "NOT_FOUND", f"no goal {gid}")
        return
    _json(handler, 200, goal)

def goal_create(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "goals need the daemon")
        return
    name = body.get("name")
    expression = body.get("expression")
    task = body.get("task")
    if not name or not expression or not task:
        _error(handler, 400, "BAD_REQUEST",
               "goal needs name, expression and task")
        return
    try:
        gid = ctx.daemon.journal.create_goal(
            str(name), str(expression), str(task),
            _req_int(body.get("priority", 5), "priority"))
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    _json(handler, 200, ctx.daemon.journal.get_goal(gid))

def goal_done(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "goals need the daemon")
        return
    try:
        gid = int(path[len("/v1/goals/"):-len("/done")])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST", "bad goal id")
        return
    if not ctx.daemon.journal.mark_goal_done(gid):
        _error(handler, 404, "NOT_FOUND", f"no goal {gid}")
        return
    _json(handler, 200, ctx.daemon.journal.get_goal(gid))

def goal_delete(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "goals need the daemon")
        return
    try:
        gid = int(path[len("/v1/goals/"):])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST", "bad goal id")
        return
    if not ctx.daemon.journal.delete_goal(gid):
        _error(handler, 404, "NOT_FOUND", f"no goal {gid}")
        return
    _json(handler, 200, {"ok": True, "deleted": gid})