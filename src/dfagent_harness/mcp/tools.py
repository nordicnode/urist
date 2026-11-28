"""The six MCP tools: schemas and dispatch.

Each tool maps onto an existing daemon HTTP route; nothing here
drives the game directly. Argument validation is strict: a
missing required argument, a wrong type, or an unknown argument
key fails with a message naming the argument and the legal shape
(the repo's malformed-input rule). A validation failure raises
:class:`ToolArgumentError` (the protocol layer turns it into a
JSON-RPC ``-32602``); anything the daemon refuses, or any
transport failure, comes back as a tool result with
``isError: true`` quoting the daemon's own message.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .client import DaemonClient, DaemonError

# Legal wiki modes (wiki.py MODES) and journal domains
# (planner.Journal domains). Stated in words in the schemas, not
# as enums: the schemas never carry an enum, per GOAL.md step 8.
WIKI_MODES = ("search", "semantic", "hybrid", "title")
JOURNAL_DOMAINS = ("threat", "needs", "nobles", "production", "expansion")
JOURNAL_SOURCES = ("decisions", "diary")

# Actions the MCP layer refuses outright, even though the HTTP
# route would run them: the daemon owns the clock (no pause), and
# UI keystrokes are never a game action (repo AGENTS.md).
_REFUSED_ACTIONS = {
    "pause": "the daemon owns the clock; MCP tools never pause or unpause the game",
    "key": "UI keystrokes are never a game action; use a typed catalog action instead",
}

# Read-only /v1/ routes `query` accepts, besides the ones other
# tools own. Exact paths, plus prefixes for /v1/unit/<id> and
# /v1/area/<id|name>.
_QUERY_EXACT = {
    "/v1/state", "/v1/status", "/v1/units", "/v1/buildings",
    "/v1/stocks", "/v1/jobs", "/v1/items", "/v1/reports",
    "/v1/map", "/v1/wealth", "/v1/slice", "/v1/column",
    "/v1/overview", "/v1/areas", "/v1/path", "/v1/survey",
    "/v1/sites", "/v1/attention", "/v1/cursor", "/v1/pause",
}
_QUERY_PREFIXES = ("/v1/unit/", "/v1/area/")

# Routes that belong to another tool: refused with a message
# naming the right tool.
_QUERY_OWNED = {
    "/v1/snapshot": "observe",
    "/v1/catalog": "catalog",
    "/v1/journal": "journal",
    "/v1/diary": "journal",
    "/v1/diary.html": "journal",
    "/v1/wiki": "wiki_search",
}


class ToolArgumentError(ValueError):
    """A tools/call argument failed validation."""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "observe",
        "description": (
            "The per-tick snapshot of the fort: diffs, attention, "
            "index, and the suggestion. The only tool called every "
            "tick. The snapshot is an index, not a dump; pull full "
            "detail through query."),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "act",
        "description": (
            "One catalog action by name plus its parameters. "
            "Validates the name against the catalog first; an "
            "unknown name fails with the legal values named. "
            "Look the action up with the catalog tool before "
            "calling it. Composed tasks take a task: name, for "
            "example task:brew."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "A catalog action name, for example "
                        "build_workshop, queue_job, designate_dig, "
                        "or a composed task as task:brew."),
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "The action parameters, exactly as the "
                        "catalog describes them for this action. "
                        "Omit when the action takes none."),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query",
        "description": (
            "Pull any fort state by route, when the snapshot only "
            "indexes the detail you need: units, buildings, "
            "stocks, jobs, map slices, columns, overview, areas, "
            "survey, sites, attention. Read-only routes only."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "string",
                    "description": (
                        "A read-only /v1/ route, for example "
                        "/v1/units?kind=citizens, "
                        "/v1/sites?kind=workshop, "
                        "/v1/column?x=97&y=97."),
                },
            },
            "required": ["route"],
            "additionalProperties": False,
        },
    },
    {
        "name": "catalog",
        "description": (
            "The self-describing action catalog: every action, "
            "its parameters, its constraints, and an example "
            "call, plus the composed tasks and the query routes. "
            "List it all, describe one action in full, or filter "
            "by a word."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "One action name to describe in full, for "
                        "example queue_job. Omit to list the whole "
                        "catalog."),
                },
                "search": {
                    "type": "string",
                    "description": (
                        "Filter the catalog by a word in the name "
                        "or description, for example brew. Ignored "
                        "when action is given."),
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "wiki_search",
        "description": (
            "Look up how Dwarf Fortress works in the local wiki "
            "export (4,485 pages). Use it when you do not know "
            "how something works or what to do about an event, "
            "instead of guessing. Returns slugs plus snippets; "
            "read a full page with the page argument."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The question in plain words, for example "
                        "how does brewing work."),
                },
                "mode": {
                    "type": "string",
                    "description": (
                        "search is the fast keyword fallback, "
                        "hybrid is the default and best for vague "
                        "questions, semantic is vector-only, title "
                        "matches page titles. Omit for hybrid."),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max results, default 5, clamped to 1-10."),
                },
                "page": {
                    "type": "string",
                    "description": (
                        "A wiki page slug to read in full, for "
                        "example brewing. When given, query is "
                        "ignored and the whole page is returned."),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "journal",
        "description": (
            "The fort's memory: the decision journal with "
            "per-domain counts, failure records (decisions with "
            "ok false), and the diary. The memory-retrieval path: "
            "use it when you need what happened before this tick."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max decisions returned, default 100, "
                        "clamped to 1-1000."),
                },
                "kind": {
                    "type": "string",
                    "description": (
                        "Filter by decision domain: threat, needs, "
                        "nobles, production, expansion. Omit for "
                        "all domains."),
                },
                "source": {
                    "type": "string",
                    "description": (
                        "decisions (the default) returns the "
                        "decision journal with per-domain counts; "
                        "diary returns the diary entries from "
                        "diary.md. Omit for decisions."),
                },
            },
            "additionalProperties": False,
        },
    },
]


def _ok(result: Any) -> dict[str, Any]:
    return {"content": [{"type": "text",
                         "text": json.dumps(result)}],
            "isError": False}


def _err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}],
            "isError": True}


def _check_args(tool: str, args: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolArgumentError(
            f"{tool}: arguments must be an object, got "
            f"{type(args).__name__}")
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ToolArgumentError(
            f"{tool}: unknown argument(s) {', '.join(unknown)}; "
            f"legal arguments are {', '.join(sorted(allowed))}")
    return args


def _require_str(tool: str, args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError(
            f"{tool}: {key} is required and must be a non-empty string")
    return value


def _optional_str(tool: str, args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolArgumentError(
            f"{tool}: {key} must be a string, got {type(value).__name__}")
    return value


def _optional_int(tool: str, args: dict[str, Any], key: str,
                  default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError(
            f"{tool}: {key} must be an integer, got "
            f"{type(value).__name__}")
    return max(low, min(high, value))


def _daemon_error_text(exc: DaemonError) -> str:
    return (f"daemon error {exc.code} (HTTP {exc.status}): "
            f"{exc.message}")


def dispatch(client: DaemonClient, name: str,
             arguments: Any) -> dict[str, Any]:
    """Run one tool. Raises ToolArgumentError for bad arguments;
    returns an isError result for everything the daemon refuses
    or any transport failure."""
    handlers = {
        "observe": _observe,
        "act": _act,
        "query": _query,
        "catalog": _catalog,
        "wiki_search": _wiki_search,
        "journal": _journal,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ToolArgumentError(f"unknown tool {name!r}")
    return handler(client, arguments)


def _observe(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    _check_args("observe", arguments, set())
    try:
        return _ok(client.get("/v1/snapshot", timeout=180))
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))


def _act(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    args = _check_args("act", arguments, {"action", "parameters"})
    action = _require_str("act", args, "action")
    params = args.get("parameters", {})
    if not isinstance(params, dict):
        raise ToolArgumentError(
            "act: parameters must be an object, got "
            f"{type(params).__name__}")
    if "/" in action:
        raise ToolArgumentError(
            "act: an action name has no '/' in it")
    if action in _REFUSED_ACTIONS:
        return _err(f"act: {action!r} is refused: "
                    f"{_REFUSED_ACTIONS[action]}")
    # Validate the name against the catalog before calling
    # anything, so an unknown name fails naming the legal values.
    try:
        client.get("/v1/catalog/" + urllib.parse.quote(action, safe=":"),
                   timeout=30)
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))
    try:
        if action.startswith("task:"):
            result = client.post(
                "/v1/tasks/" + urllib.parse.quote(action[len("task:"):],
                                                 safe=""), {})
        else:
            result = client.post(
                "/v1/actions/" + urllib.parse.quote(action, safe=""),
                params)
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))
    # A failed action (ok false) is a result, not an error: the
    # action ran and its envelope (with `fix`) is the answer.
    return _ok(result)


def _query(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    args = _check_args("query", arguments, {"route"})
    route = _require_str("query", args, "route")
    parts = urllib.parse.urlsplit(route)
    path = parts.path
    if not route.startswith("/v1/"):
        return _err(
            "query: route must start with /v1/, got "
            f"{route!r}; give a read-only /v1/ route such as "
            "/v1/units or /v1/sites?kind=workshop")
    owned = _QUERY_OWNED.get(path)
    if owned is not None or path.startswith("/v1/catalog/") \
            or path.startswith("/v1/wiki/") \
            or path.startswith("/v1/memory/"):
        tool = owned or (
            "catalog" if path.startswith("/v1/catalog/")
            else "wiki_search" if path.startswith("/v1/wiki/")
            else "journal")
        return _err(
            f"query: {path} belongs to the {tool} tool; use that "
            "tool instead of query for it")
    if path.startswith(("/v1/actions/", "/v1/tasks/", "/v1/control/",
                        "/v1/goals", "/v1/events")):
        return _err(
            f"query: {path} is not a read-only route; actions go "
            "through the act tool")
    if path not in _QUERY_EXACT and not any(
            path.startswith(p) for p in _QUERY_PREFIXES):
        return _err(
            f"query: {path} is not a known read-only route; "
            "known routes are /v1/state, /v1/status, /v1/units, "
            "/v1/unit/<id>, /v1/buildings, /v1/stocks, /v1/jobs, "
            "/v1/items, /v1/reports, /v1/map, /v1/wealth, "
            "/v1/slice, /v1/column, /v1/overview, /v1/areas, "
            "/v1/area/<id|name>, /v1/path, /v1/survey, /v1/sites, "
            "/v1/attention, /v1/cursor, /v1/pause")
    try:
        return _ok(client.get(route))
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))


def _catalog(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    args = _check_args("catalog", arguments, {"action", "search"})
    action = _optional_str("catalog", args, "action")
    search = _optional_str("catalog", args, "search")
    try:
        if action is not None:
            if "/" in action:
                raise ToolArgumentError(
                    "catalog: an action name has no '/' in it")
            return _ok(client.get(
                "/v1/catalog/" + urllib.parse.quote(action, safe=":"),
                timeout=30))
        result = client.get("/v1/catalog", timeout=30)
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))
    if search is None:
        return _ok(result)
    needle = search.strip().lower()
    if not needle:
        return _ok(result)
    matches = [a for a in result.get("actions", [])
               if needle in a.get("name", "").lower()
               or needle in a.get("about", "").lower()]
    tasks = [t for t in result.get("tasks", [])
             if needle in t.get("name", "").lower()
             or needle in str(t.get("about", "")).lower()]
    return _ok({"actions": matches, "tasks": tasks,
                "count": len(matches) + len(tasks),
                "searched": search})


def _wiki_search(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    args = _check_args(
        "wiki_search", arguments, {"query", "mode", "limit", "page"})
    query = _require_str("wiki_search", args, "query")
    mode = _optional_str("wiki_search", args, "mode")
    if mode is not None and mode not in WIKI_MODES:
        raise ToolArgumentError(
            "wiki_search: mode must be one of "
            f"{', '.join(WIKI_MODES)}, got {mode!r}")
    limit = _optional_int("wiki_search", args, "limit", 5, 1, 10)
    page = _optional_str("wiki_search", args, "page")
    if page is not None:
        if "/" in page:
            raise ToolArgumentError(
                "wiki_search: a page slug has no '/' in it")
        try:
            return _ok(client.get(
                "/v1/wiki/" + urllib.parse.quote(page, safe=""),
                timeout=180))
        except DaemonError as exc:
            return _err(_daemon_error_text(exc))
    params = {"q": query,
              "mode": mode or "hybrid",
              "limit": str(limit)}
    route = "/v1/wiki?" + urllib.parse.urlencode(params)
    try:
        return _ok(client.get(route, timeout=180))
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))


def _journal(client: DaemonClient, arguments: Any) -> dict[str, Any]:
    args = _check_args("journal", arguments, {"limit", "kind", "source"})
    limit = _optional_int("journal", args, "limit", 100, 1, 1000)
    kind = _optional_str("journal", args, "kind")
    if kind is not None and kind not in JOURNAL_DOMAINS:
        raise ToolArgumentError(
            "journal: kind must be one of "
            f"{', '.join(JOURNAL_DOMAINS)}, got {kind!r}")
    source = _optional_str("journal", args, "source") or "decisions"
    if source not in JOURNAL_SOURCES:
        raise ToolArgumentError(
            "journal: source must be one of "
            f"{', '.join(JOURNAL_SOURCES)}, got {source!r}")
    if source == "diary" and kind is not None:
        raise ToolArgumentError(
            "journal: kind only applies to source decisions, "
            "not to source diary")
    try:
        if source == "diary":
            return _ok(client.get("/v1/diary"))
        route = f"/v1/journal?limit={limit}"
        if kind is not None:
            route += "&kind=" + urllib.parse.quote(kind, safe="")
        return _ok(client.get(route))
    except DaemonError as exc:
        return _err(_daemon_error_text(exc))
