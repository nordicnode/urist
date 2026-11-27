from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json


def wiki(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Wiki lookup (GOAL.md step 5, layer 6): the agent asks
    # the harness for DF knowledge; the harness answers from
    # the local wiki export. No game read. mode=search is
    # the fast keyword fallback; hybrid (the default) fuses
    # FTS + semantic and is best for vague questions.
    q = query.get("q", [""])[0].strip()
    if not q:
        _error(handler, 400, "BAD_REQUEST",
               "missing ?q= (the question to look up)")
        return
    mode = query.get("mode", ["hybrid"])[0]
    try:
        limit = int(query.get("limit", ["5"])[0])
    except ValueError:
        limit = 5
    from .. import wiki as wiki_mod
    try:
        result = wiki_mod.wiki_search(
            q, mode=mode, limit=max(1, min(limit, 10)))
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    except RuntimeError as exc:
        _error(handler, 503, "WIKI_UNAVAILABLE", str(exc))
        return
    _json(handler, 200, result)

def wiki_page(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Dump a whole wiki page by slug.
    slug = path[len("/v1/wiki/"):]
    if not slug or "/" in slug:
        _error(handler, 400, "BAD_REQUEST",
               "a wiki page slug has no '/' in it")
        return
    from .. import wiki as wiki_mod
    try:
        result = wiki_mod.wiki_page(slug)
    except RuntimeError as exc:
        _error(handler, 503, "WIKI_UNAVAILABLE", str(exc))
        return
    _json(handler, 200, result)