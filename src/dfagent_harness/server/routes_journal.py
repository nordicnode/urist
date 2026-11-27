from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json


def journal(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "daemon journal is not available in this mode")
        return
    try:
        limit = int(query.get("limit", ["100"])[0])
    except ValueError:
        limit = 100
    kind = query.get("kind", [None])[0]
    decisions = ctx.daemon.journal.recent_decisions(
        limit=max(1, min(limit, 1000)))
    if kind:
        decisions = [d for d in decisions
                     if d.get("domain") == kind]
    _json(handler, 200, {"decisions": decisions,
                      "counts": ctx.daemon.journal.decision_counts()})

def diary_read(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # The diary: entries parsed from diary.md in the daemon
    # state dir. No game read.
    from ..daemon import default_state_dir
    from ..diary import diary_md_path, parse_entries
    state_dir = ctx.daemon.state_dir if ctx.daemon is not None \
        else default_state_dir()
    md_path = diary_md_path(state_dir)
    entries = parse_entries(md_path.read_text()) \
        if md_path.exists() else []
    _json(handler, 200, {"entries": entries,
                      "count": len(entries)})

def diary_html(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Serve the generated diary.html as a page.
    from ..daemon import default_state_dir
    from ..diary import diary_html_path
    state_dir = ctx.daemon.state_dir if ctx.daemon is not None \
        else default_state_dir()
    html_path = diary_html_path(state_dir)
    if not html_path.exists():
        _error(handler, 404, "NOT_FOUND",
               "no diary yet — the fort has not lived a day")
        return
    body = html_path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def memory_why(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Death investigation: why did this dwarf die? The
    # Store's death record + diagnosis + the unit's history,
    # in plain words. No game read.
    try:
        unit_id = int(path[len("/v1/memory/why/"):])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST",
               "unit id must be an integer")
        return
    store = ctx.daemon.store if ctx.daemon is not None \
        else ctx.default_store()
    deaths = [d for d in store.deaths()
              if d.get("unit_id") == unit_id]
    if not deaths:
        _error(handler, 404, "NOT_FOUND",
               f"no death recorded for unit {unit_id}")
        return
    death = deaths[-1]
    history = store.unit_history(unit_id)
    _json(handler, 200, {
        "unit_id": unit_id,
        "death": death,
        "history": history,
        "answer": (
            f"Unit {unit_id} died at tick "
            f"{death.get('tick')} ({death.get('cause')}). "
            f"History: {len(history)} daily samples; "
            f"last sample {history[-1] if history else None}."),
    })

def memory_summary(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Re-grounding: the current situation + open problems +
    # recent failures, for a new session or a compacted
    # context. No game read — Store + Journal.
    store = ctx.daemon.store if ctx.daemon is not None \
        else ctx.default_store()
    journal = ctx.daemon.journal if ctx.daemon is not None else None
    summary: dict[str, Any] = {
        "deaths": store.deaths()[-5:],
        "trends": {},
    }
    for metric in ("drink", "food", "wood", "population"):
        pts = store.trend_samples(metric)
        if pts:
            summary["trends"][metric] = {
                "latest": pts[-1][1],
                "days_remaining": store.days_remaining(
                    metric, pts[-1][0]),
            }
    if journal is not None:
        summary["recent_decisions"] = \
            journal.recent_decisions(limit=10)
        summary["recent_events"] = journal.recent_events(
            limit=10)
        # Failures: decisions that did not work, most recent.
        summary["failures"] = [
            d for d in journal.recent_decisions(limit=100)
            if d.get("ok") is False][:5]
    _json(handler, 200, summary)

def diary_write(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # POST /v1/control/diary — write the diary entry for a
    # completed M1 day. The daemon's planner loop is paused
    # during M1 runs, so its day-boundary trigger never
    # fires there; the driver calls this at day-complete run
    # end instead. The summary is built from the Store +
    # Journal exactly like the daemon trigger; the driver's
    # own record (its decisions + the run's start/end stocks,
    # parsed from its snapshots) is merged in via
    # diary.merge_driver_record — the run's decisions are not
    # in the Journal and no trend samples are taken while
    # the loop is paused. The entry itself is AI-written
    # (diary.write_ai_entry) from the per-dwarf feed — the
    # template renderer is retired from the write path
    # (Mikey: it reads as a list, not a diary entry). The
    # driver's run-end citizens are recorded first, so the
    # feed has today's per-dwarf samples. write_ai_body is
    # idempotent per date, so a later daemon-trigger write
    # for the same day replaces rather than duplicates. On
    # model failure the day is skipped (503 DIARY_FAILED);
    # a template list is never written instead.
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "diary needs the daemon")
        return
    day_start = body.get("day_start_tick")
    if not isinstance(day_start, int):
        _error(handler, 400, "BAD_REQUEST",
               "day_start_tick (int) is required")
        return
    year = body.get("year") or 0
    fort = body.get("fort_name") or ""
    from ..diary import (build_diary_feed,
                        merge_driver_record, write_ai_entry)
    from ..dwarves import record_citizens
    from ..freepi import FreePiClient
    try:
        citizens = body.get("citizens") or []
        if citizens:
            # The run-end citizens are the dwarves' state at
            # the end of the entry's day; clamp the stamp to
            # the day's last tick so the feed sees them as
            # the day's current sample (the run itself ends
            # part-way into the next day).
            tick_end = day_start + 1200 - 1
            record_citizens(ctx.daemon.store, tick_end,
                            citizens)
        citizens_start = body.get("citizens_start") or []
        tick_start = body.get("tick_start")
        if citizens_start and isinstance(tick_start, int):
            record_citizens(ctx.daemon.store, tick_start,
                            citizens_start)
        # Fresh stocks at the same moment as the run-end
        # citizens: the entry's closing numbers must come
        # from the same fresh run-end collect as the
        # per-dwarf samples, not a stale trend sample (run
        # 060346: the trend sample said drink 39, the live
        # game said 38 — two moments, two numbers). The
        # game is paused at run end, so this collect and
        # the citizens' values describe the same moment.
        # Best-effort: a failed collect falls back to the
        # driver's posted stocks, never fails the write.
        stocks_end = body.get("stocks_end") or {}
        try:
            fresh = ctx.collect_section("stocks")
            stocks = (fresh or {}).get("stocks") or {}
            fresh_end: dict[str, Any] = {}
            for key, field in (
                    ("drink", "drink_units"),
                    ("food", "food_units"),
                    ("wood", "wood_units"),
                    ("stone", "stone_units")):
                val = stocks.get(field)
                if isinstance(val, int):
                    fresh_end[key] = val
            if citizens:
                fresh_end["population"] = len(citizens)
            if fresh_end:
                stocks_end = fresh_end
        except Exception:  # noqa: BLE001 - best-effort
            pass
        feed = build_diary_feed(
            ctx.daemon.store, ctx.daemon.journal, day_start, fort,
            year, state_dir=ctx.daemon.state_dir)
        merge_driver_record(
            feed["summary"],
            decisions=body.get("decisions") or [],
            stocks_start=body.get("stocks_start") or {},
            stocks_end=stocks_end)
        path = write_ai_entry(FreePiClient(),
                              feed, ctx.daemon.state_dir)
    except Exception as exc:  # noqa: BLE001 - best-effort
        _error(handler, 503, "DIARY_FAILED",
               f"diary write failed: {exc}")
        return
    _json(handler, 200, {"ok": True,
                      "date": feed["summary"]["date"],
                      "path": str(path)})