"""Shared helpers for the agent-facing HTTP server.

Response writing, request coercion, route matchers, and the SDL
keysyms — the small pieces every route module needs. Moved verbatim
out of the old monolithic ``server.py`` (item-19 refactor).
"""
from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Optional

HEALTH_PATH = "/v1/health"
_HEARTBEAT_SECONDS = 30.0

#: SDL 1.2 keysyms for PassKeyboardEvent (PROTOCOL.md §2.6).
KEYSYMS: dict[str, int] = {
    "down": 274, "up": 273, "left": 276, "right": 275,
    "enter": 13, "return": 13, "escape": 27, "esc": 27,
    "space": 32, "tab": 9, "backspace": 8,
    "pageup": 280, "pagedown": 281, "home": 278, "end": 279,
    "delete": 127, "insert": 277,
    "f1": 282, "f2": 283, "f3": 284, "f4": 285, "f5": 286,
    "f6": 287, "f7": 288, "f8": 289, "f9": 290, "f10": 291,
    "f11": 292, "f12": 293,
}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    KEYSYMS.setdefault(_c, ord(_c))
for _c in ",./;'[]\\-=":
    KEYSYMS.setdefault(_c, ord(_c))


def _needs_still_site(state: dict) -> bool:
    """True when the snapshot's suggestion would be a still build:
    drink is low and no Still exists. Used by _snapshot to decide
    whether deriving free workshop sites is worth the ~1 s cost —
    the snapshot never triggers a scan otherwise. The threshold is
    drink < 50, matching the proactive still suggestion in
    assembler.suggest (a still takes days to build + brew, so the
    model needs the site well before drink is critical)."""
    stocks = state.get("stocks") or {}
    drink = stocks.get("drink_units")
    if not isinstance(drink, int) or drink >= 50:
        return False
    buildings = state.get("buildings") or {}
    for b in buildings.get("list") or []:
        if b.get("type") == "Workshop" and b.get("subtype") == "Still":
            return False
    return True

def _request_id() -> str:
    return uuid.uuid4().hex[:12]

def _error(handler: BaseHTTPRequestHandler, status: int, code: str,
           message: str, detail: Optional[dict[str, Any]] = None) -> None:
    body = json.dumps({
        "error": {"code": code, "message": message,
                  "detail": detail or {}},
        "request_id": _request_id(),
    }).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass

def _json(handler: BaseHTTPRequestHandler, status: int,
          payload: Any) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        # Client went away mid-response (e.g. dfh status timing
        # out); not an error worth a traceback in the daemon log.
        pass

def _sse_event(seq: int, payload: dict[str, Any]) -> bytes:
    return (f"id: {seq}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            ).encode()

def _action_envelope(result: Any) -> dict[str, Any]:
    """Normalise an ActionResult (or dict) to the §4.1 envelope."""
    if isinstance(result, dict):
        return result
    return result.to_dict()

def _cursor_array(value: Any) -> list[Any]:
    """Coerce a cursor value to the documented [x, y, z] array.

    The Lua side wraps the cursor in dfh_arr(), so a live read is
    already a list. A dict with string keys "1"/"2"/"3" is the old
    plain-table encoding (H10) — normalize it instead of serving
    the wrong shape. Anything else is [None] * 3.
    """
    if isinstance(value, list):
        return (value + [None] * 3)[:3]
    if isinstance(value, dict):
        try:
            return [value["1"], value["2"], value["3"]]
        except KeyError:
            pass
    return [None] * 3

def _req_int(value: Any, field: str,
             default: Optional[int] = None) -> int:
    """Coerce a client-supplied value to int, or raise ValueError.

    Raises on None (missing field), bools, non-numeric strings and
    non-integral floats. A client-input error, mapped to 400 by
    the caller — never a 502 and never a dropped connection (T3).
    """
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"bad {field}: missing")
    if isinstance(value, bool):
        raise ValueError(f"bad {field}: {value!r} is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise ValueError(
                f"bad {field}: {value!r} is not an integer") from None
    raise ValueError(f"bad {field}: {value!r} is not an integer")

def _req_float(value: Any, field: str,
               default: Optional[float] = None) -> float:
    """Coerce a client-supplied value to float, or raise ValueError."""
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"bad {field}: missing")
    if isinstance(value, bool):
        raise ValueError(f"bad {field}: {value!r} is not a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise ValueError(
                f"bad {field}: {value!r} is not a number") from None
    raise ValueError(f"bad {field}: {value!r} is not a number")

def _req_seq(value: Any, field: str, length: int) -> tuple[int, ...]:
    """Coerce a client-supplied value to a tuple of `length` ints.

    Raises ValueError on None, non-sequences, strings and wrong
    lengths — the `tuple(body.get("box"))` TypeError that used to
    escape as a 502 (T3 row 1).
    """
    if value is None:
        raise ValueError(f"bad {field}: missing")
    if isinstance(value, (str, bytes)):
        raise ValueError(f"bad {field}: must be a list of {length}")
    try:
        items = tuple(value)
    except TypeError:
        raise ValueError(
            f"bad {field}: must be a list of {length}") from None
    if len(items) != length:
        raise ValueError(
            f"bad {field}: want {length} items, got {len(items)}")
    return tuple(_req_int(item, f"{field}[{i}]")
                 for i, item in enumerate(items))

def _exact(path: str) -> Callable[[str], bool]:
    return lambda p: p == path

def _prefix(prefix: str) -> Callable[[str], bool]:
    return lambda p: p.startswith(prefix)

def _prefix_suffix(prefix: str, suffix: str) -> Callable[[str], bool]:
    return lambda p: p.startswith(prefix) and p.endswith(suffix)
