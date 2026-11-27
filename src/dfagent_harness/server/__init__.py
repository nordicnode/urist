"""Agent-facing HTTP server for the DF Agent Harness (phase 4).

Stdlib only (``http.server``). The daemon (``daemon.py``) owns the
one DFHack RPC connection; this module serves it over HTTP/JSON on
``127.0.0.1`` only, with optional bearer-token auth (PROTOCOL.md
§3.3) and the typed action endpoints (PROTOCOL.md §4).

Routes:

* ``GET /v1/health`` — liveness, no auth required.
* ``GET /v1/state`` — full snapshot (poller snapshot when fresh,
  else a fresh collect).
* ``GET /v1/snapshot`` — the per-tick assembled snapshot
  (world-model design §6): full paused collect folded through the
  Context Assembler with the Store (diffing + trends) and the
  poller's detector (attention). Areas + survey from cache only.
* ``GET /v1/status`` — compact status (population, stocks, threats).
* ``GET /v1/units``, ``/v1/unit/{id}``, ``/v1/buildings``,
  ``/v1/jobs``, ``/v1/items``, ``/v1/reports``, ``/v1/map``,
  ``/v1/wealth``, ``/v1/cursor`` — read-only state queries.
  ``GET /v1/stocks`` is a fresh stocks collect (drink/food/wood
  units), not the poller's cached state — it is the pre-flight
  gate's source of truth for drink (see below).
  ``/v1/wealth`` is on-demand only (a per-run measurement, not a
  per-tick signal): fortress value as the sum of item values over
  the fort's own items — see lua/wealth.lua and docs/SCORING.md
  for the exact definition and what it is not.
* ``GET /v1/slice?x0&y0&z&x1&y1&layer`` — one ASCII slice
  (world-model design §3.4; max 64x64, ``&full=1`` for a full
  z-level, flagged expensive). Coordinate rulers, the fort-centre
  landmark, the areas overlapping the rect, and what is directly
  above and below the slice, in plain words.
* ``GET /v1/column?x&y[&from_z=N][&levels=N]`` — vertical profile
  of one map column (standing directive 2026-11-26): strata from
  the top down in plain words, hazards (aquifer/magma/water), and
  the answer to "if I dig down N levels from here, what do I hit?"
* ``GET /v1/overview`` — coarse block-level overview of the whole
  map (a side cross-section through the fort + a top-down view of
  the fort's level), built from the cached scan + survey, no game
  read.
* ``GET /v1/areas``, ``/v1/area/{id|name}``, ``/v1/path?a&b`` —
  named areas + the connectivity graph (design §3; derived once
  from a full block scan, cached, ``?refresh=1`` re-derives).
  Every area carries a plain-words ``description`` (what it is,
  where, how big, what is in it, how to get there, what is above
  and below it).
* ``GET /v1/survey[?kind=water|magma|mineral|aquifer|plants|soil]``
  — resource survey (design §5; one ~25 s scan, cached, stale
  after one season; ``?refresh=1`` re-scans). Plain-words summary,
  nearest of each kind, vertical facts, hazards, cost.
* ``GET /v1/sites?kind=workshop|stockpile|zone|farm_plot|furniture|
  trap|room[&w=N][&h=N]`` — verified-free placement sites for a
  kind + size (the full detail behind the snapshot's compact
  placement section): each site verified free (terrain, occupancy,
  plants, units, overlap) AND reachable by a dwarf from the fort
  centre, with why each is good, plus the top blocked candidates
  with their reasons. Never guess coordinates — use these.
* ``GET /v1/attention`` — the attention section (design §6.1):
  threats first, then new arrivals, in plain words with position
  and class. Needs the daemon's poller (its diff record).
* ``GET /v1/journal`` — daemon journal (decisions + events).
* ``GET /v1/goals``, ``POST /v1/goals``, ``GET /v1/goals/{id}``,
  ``POST /v1/goals/{id}/done``, ``DELETE /v1/goals/{id}``.
* ``GET /v1/tasks``, ``GET /v1/tasks/{name}/plan``,
  ``POST /v1/tasks/{name}`` — composed tasks.
* ``GET /v1/events`` — SSE stream (``Accept: text/event-stream``)
  or JSON array (``?limit=N`` / ``?since=N``).
* ``POST /v1/actions/{pause,dig,undesignate,chop,gather,build,
  deconstruct,stockpile,order,order-remove,queue-job,labor,key,
  cursor,lua,command}`` — verified actions (action envelope).
  ``lua``/``command`` are guarded: disabled unless the daemon was
  started with ``allow_raw_actions``.
* ``POST /v1/control/quicksave``,
  ``GET /v1/control/daemon``,
  ``POST /v1/control/daemon/pause|resume`` — daemon control.
* ``POST /v1/control/diary`` — write the diary entry for a
  completed M1 day (the driver calls it at day-complete run end;
  the daemon's own day-boundary trigger cannot fire while its loop
  is paused for an M1 run).

Errors follow PROTOCOL.md §6: HTTP status + ``{"error": {"code",
"message", "detail": ...}, "request_id": ...}``. ``503
GAME_NOT_RUNNING`` when the game is unreachable.

Package layout (item-19 refactor): ``helpers`` (response writing,
request coercion, route matchers), ``context`` (the ServerContext
the old nested Handler closed over), ``handler`` (thin plumbing +
the ROUTES table), ``routes_*`` (one module per resource), and
``factory`` (``create_server`` / ``run_server``).
"""

from __future__ import annotations

from .factory import create_server, run_server
from .helpers import (
    _cursor_array,
    _req_float,
    _req_int,
    _req_seq,
    HEALTH_PATH,
    KEYSYMS,
)

__all__ = ["create_server", "run_server", "HEALTH_PATH", "KEYSYMS",
           "_cursor_array", "_req_float", "_req_int", "_req_seq"]
