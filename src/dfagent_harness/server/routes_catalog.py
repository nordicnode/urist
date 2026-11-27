from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json


def catalog(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # The self-describing catalog: every action, its
    # parameters, its constraints, an example call. Built
    # from the code, so it cannot drift from what the
    # harness actually does. No game read — it works even
    # with the game down.
    from .. import catalog as catalog_mod
    _json(handler, 200, catalog_mod.catalog())

def catalog_one(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # One action's description, by name.
    name = path[len("/v1/catalog/"):]
    if not name or "/" in name:
        _error(handler, 400, "BAD_REQUEST",
               "an action name has no '/' in it")
        return
    from .. import catalog as catalog_mod
    desc = catalog_mod.describe(name)
    if desc is None:
        from ..actions import ACTIONS
        from ..daemon import TASK_DEFS
        _error(handler, 404, "UNKNOWN_ACTION",
               f"no action named {name!r} — choose from: "
               f"{', '.join(sorted(ACTIONS))} or a task: "
               f"{', '.join('task:' + t for t in sorted(TASK_DEFS))}")
        return
    _json(handler, 200, desc)