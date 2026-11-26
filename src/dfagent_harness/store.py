"""State Store: the world model's system of record (world.db).

Design §9: one SQLite file in the daemon's state dir
(``~/.config/df-agent-harness/world.db``), alongside the planner's
``journal.db`` (which keeps decisions, daemon_events, and goals — no
migration risk). The two are joined by ``tick``. The Store is the
system of record; the agent's context is a cache of it.

Tables (design §9):
- ``snapshots``: last full snapshot per section — the diff baseline
  for the assembler (tick, section, hash, json).
- ``areas``: the spatial model (§3) — one row per area, versioned.
- ``survey``: one row per survey kind (water/magma/veins/soil/
  plants), versioned.
- ``trends``: daily samples of drink/food/wood/stone/population/
  wealth (metric, tick, value). The 7-day slope and days-remaining
  are computed here, never from a single snapshot.
- ``unit_history``: per-citizen daily samples — what the death
  investigation loop reads.
- ``deaths``: death records with the harness's diagnosis (from the
  unit's history + the reports), not the game's text.

Everything is timestamped in game time (year_tick). A day is 1,200
ticks; a season 33,600; a year 403,200.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

__all__ = ["Store", "TICKS_PER_DAY", "TICKS_PER_SEASON",
           "TICKS_PER_YEAR", "diagnose_death"]

TICKS_PER_DAY = 1200
TICKS_PER_SEASON = 33600
TICKS_PER_YEAR = 403200

# How far back a trend slope looks (in-game days).
TREND_WINDOW_DAYS = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    section TEXT PRIMARY KEY,
    tick INTEGER NOT NULL,
    hash TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS areas (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    x0 INTEGER NOT NULL, y0 INTEGER NOT NULL, z0 INTEGER NOT NULL,
    x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, z1 INTEGER NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    connections_json TEXT NOT NULL DEFAULT '[]',
    derived_at_tick INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    stale INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS survey (
    kind TEXT PRIMARY KEY,
    tick INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    hash TEXT NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trends (
    metric TEXT NOT NULL,
    tick INTEGER NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (metric, tick)
);
CREATE TABLE IF NOT EXISTS unit_history (
    unit_id INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    pos_json TEXT NOT NULL DEFAULT '[]',
    job TEXT NOT NULL DEFAULT '',
    hunger INTEGER NOT NULL DEFAULT 0,
    thirst INTEGER NOT NULL DEFAULT 0,
    sleepiness INTEGER NOT NULL DEFAULT 0,
    stress INTEGER NOT NULL DEFAULT 0,
    wounds_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (unit_id, tick)
);
CREATE TABLE IF NOT EXISTS deaths (
    unit_id INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    cause TEXT NOT NULL,
    history_ref TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (unit_id, tick)
);
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def diagnose_death(unit_id: int,
                   history: list[dict[str, Any]],
                   reports: Optional[list[str]] = None
                   ) -> tuple[str, str]:
    """Diagnose why a citizen died, from its history + the reports.

    The harness's diagnosis, not the game's text. The last sample
    before death is what matters: a dwarf that died with thirst at
    the drink threshold died of thirst; one with untreated wounds
    died of its wounds. Returns (cause, history_ref) where
    history_ref is the tick of the last sample used.
    """
    if not history:
        return ("unknown — no history recorded for this dwarf", "")
    last = history[-1]
    ref = str(last.get("tick", ""))
    thirst = last.get("thirst", 0) or 0
    hunger = last.get("hunger", 0) or 0
    sleepiness = last.get("sleepiness", 0) or 0
    wounds = last.get("wounds") or last.get("wounds_json") or []
    if isinstance(wounds, str):
        try:
            wounds = json.loads(wounds)
        except (ValueError, TypeError):
            wounds = []
    # Measured thresholds (phase 1, verified live): thirst drinks
    # at ~20,000, hunger eats at ~40,000, sleepiness sleeps at
    # ~50,000. A dwarf that died with a counter at or above its
    # threshold died of that need.
    if thirst >= 20000:
        return (f"died of thirst (thirst counter {thirst}, "
                f"drinks at 20,000; no drink available)", ref)
    if hunger >= 40000:
        return (f"died of hunger (hunger counter {hunger}, "
                f"eats at 40,000; no food available)", ref)
    if wounds:
        n = len(wounds)
        return (f"died of wounds ({n} wound{'s' if n != 1 else ''} "
                f"in the last sample)", ref)
    if sleepiness >= 50000:
        return (f"died while exhausted (sleepiness {sleepiness}, "
                f"sleeps at 50,000)", ref)
    # No need at threshold and no wounds: look at the reports.
    for line in (reports or []):
        low = line.lower()
        if "died" in low or "dead" in low:
            return (f"unknown cause — last report: {line[:120]}", ref)
    return ("unknown cause — no need at threshold, no wounds in "
            "the last sample", ref)


def default_world_db_path() -> Path:
    """``~/.config/df-agent-harness/world.db`` (or
    ``$XDG_CONFIG_HOME/df-agent-harness/world.db``) — the same
    directory the daemon uses as its state dir."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "df-agent-harness" / "world.db"
    return Path.home() / ".config" / "df-agent-harness" / "world.db"


def _locked(fn):
    """Run a Store method under the instance lock (the planner
    thread and the HTTP threads share one Store)."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class Store:
    """The world.db State Store.

    Thread-safe: the daemon's planner thread and the HTTP server's
    request threads share one Store (daemon.store), so every method
    takes the instance lock and the connection is opened with
    ``check_same_thread=False``.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path),
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- snapshots (the assembler's diff baseline) -------------------
    @_locked
    def record_snapshot(self, tick: int, section: str,
                        text: str) -> str:
        """Store the last full text of one snapshot section.
        Returns the section hash."""
        h = _hash(text)
        self.conn.execute(
            "INSERT INTO snapshots (section, tick, hash, json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(section) DO UPDATE SET tick=excluded.tick,"
            " hash=excluded.hash, json=excluded.json",
            (section, tick, h, text))
        self.conn.commit()
        return h

    @_locked
    def get_snapshot(self, section: str
                     ) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT tick, hash, json FROM snapshots WHERE section=?",
            (section,)).fetchone()
        if row is None:
            return None
        return {"tick": row["tick"], "hash": row["hash"],
                "text": row["json"]}

    # -- areas ----------------------------------------------------------
    @_locked
    def record_areas(self, tick: int, areas: list[dict[str, Any]],
                     graph: Optional[dict[str, list[str]]] = None
                     ) -> None:
        """Replace the area set (one version per derivation)."""
        graph = graph or {}
        self.conn.execute("DELETE FROM areas")
        for a in areas:
            b = a["bbox"]
            self.conn.execute(
                "INSERT INTO areas (id, name, kind, x0, y0, z0, "
                "x1, y1, z1, purpose, summary_json, "
                "connections_json, derived_at_tick, version, stale) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
                (a["id"], a["name"], a["kind"],
                 b["x0"], b["y0"], b["z0"], b["x1"], b["y1"], b["z1"],
                 a.get("purpose", ""),
                 json.dumps({"blocks": a.get("blocks"),
                             "description": a.get("description", "")}),
                 json.dumps(graph.get(a["id"], [])),
                 tick))
        self.conn.commit()

    @_locked
    def get_areas(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM areas ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d.pop("summary_json") or "{}")
            d["connections"] = json.loads(
                d.pop("connections_json") or "[]")
            out.append(d)
        return out

    # -- survey ---------------------------------------------------------
    @_locked
    def record_survey(self, tick: int, kind: str,
                      data: dict[str, Any]) -> str:
        text = json.dumps(data, sort_keys=True)
        h = _hash(text)
        self.conn.execute(
            "INSERT INTO survey (kind, tick, data_json, hash, stale) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(kind) DO UPDATE SET tick=excluded.tick,"
            " data_json=excluded.data_json, hash=excluded.hash,"
            " stale=0",
            (kind, tick, text, h))
        self.conn.commit()
        return h

    @_locked
    def get_survey(self, kind: str) -> Optional[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT tick, data_json, hash, stale FROM survey "
            "WHERE kind=?", (kind,)).fetchone()
        if row is None:
            return None
        return {"tick": row["tick"],
                "data": json.loads(row["data_json"]),
                "hash": row["hash"], "stale": bool(row["stale"])}

    # -- trends ---------------------------------------------------------
    @_locked
    def sample_trend(self, tick: int, metric: str,
                     value: float) -> None:
        """One daily sample. Same (metric, tick) overwrites."""
        self.conn.execute(
            "INSERT INTO trends (metric, tick, value) VALUES (?, ?, ?)"
            " ON CONFLICT(metric, tick) DO UPDATE SET "
            "value=excluded.value",
            (metric, tick, value))
        self.conn.commit()

    @_locked
    def trend_samples(self, metric: str,
                      since_tick: Optional[int] = None
                      ) -> list[tuple[int, float]]:
        if since_tick is None:
            rows = self.conn.execute(
                "SELECT tick, value FROM trends WHERE metric=? "
                "ORDER BY tick", (metric,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT tick, value FROM trends WHERE metric=? "
                "AND tick >= ? ORDER BY tick",
                (metric, since_tick)).fetchall()
        return [(r["tick"], r["value"]) for r in rows]

    @_locked
    def burn_rate(self, metric: str, tick: int,
                  days: int = TREND_WINDOW_DAYS) -> Optional[float]:
        """Slope (units per in-game day) over the last ``days`` days.

        Least-squares over the samples in the window. Positive
        means the stock is FALLING (burning). None when fewer than
        two samples or no time span.
        """
        since = tick - days * TICKS_PER_DAY
        pts = self.trend_samples(metric, since_tick=since)
        if len(pts) < 2:
            return None
        xs = [(t - pts[0][0]) / TICKS_PER_DAY for t, _ in pts]
        ys = [v for _, v in pts]
        n = len(pts)
        mx = sum(xs) / n
        my = sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return None
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        # Slope is change per day; falling stock has negative
        # slope — burn rate is the positive fall.
        return -slope

    @_locked
    def days_remaining(self, metric: str, tick: int,
                       days: int = TREND_WINDOW_DAYS
                       ) -> Optional[float]:
        """Stock / burn rate, in in-game days. None when the stock
        is not falling, or there is no slope to compute from."""
        rate = self.burn_rate(metric, tick, days=days)
        if rate is None or rate <= 0:
            return None
        pts = self.trend_samples(metric)
        if not pts:
            return None
        current = pts[-1][1]
        if current <= 0:
            return 0.0
        return current / rate

    # -- unit history ---------------------------------------------------
    @_locked
    def record_unit_history(self, tick: int, unit_id: int,
                            pos: Optional[list[int]] = None,
                            job: str = "",
                            hunger: int = 0, thirst: int = 0,
                            sleepiness: int = 0, stress: int = 0,
                            wounds: Optional[list] = None) -> None:
        self.conn.execute(
            "INSERT INTO unit_history (unit_id, tick, pos_json, job,"
            " hunger, thirst, sleepiness, stress, wounds_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(unit_id, tick) DO UPDATE SET "
            "pos_json=excluded.pos_json, job=excluded.job,"
            " hunger=excluded.hunger, thirst=excluded.thirst,"
            " sleepiness=excluded.sleepiness,"
            " stress=excluded.stress,"
            " wounds_json=excluded.wounds_json",
            (unit_id, tick, json.dumps(pos or []), job,
             hunger, thirst, sleepiness, stress,
             json.dumps(wounds or [])))
        self.conn.commit()

    @_locked
    def unit_history(self, unit_id: int,
                     limit: Optional[int] = None
                     ) -> list[dict[str, Any]]:
        q = ("SELECT * FROM unit_history WHERE unit_id=? "
             "ORDER BY tick")
        args: tuple = (unit_id,)
        if limit is not None:
            q += " LIMIT ?"
            args = (unit_id, limit)
        rows = self.conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["pos"] = json.loads(d.pop("pos_json") or "[]")
            d["wounds"] = json.loads(d.pop("wounds_json") or "[]")
            out.append(d)
        return out

    # -- deaths ---------------------------------------------------------
    @_locked
    def record_death(self, tick: int, unit_id: int, cause: str,
                     history_ref: str = "") -> None:
        self.conn.execute(
            "INSERT INTO deaths (unit_id, tick, cause, history_ref) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(unit_id, tick) DO UPDATE SET "
            "cause=excluded.cause, history_ref=excluded.history_ref",
            (unit_id, tick, cause, history_ref))
        self.conn.commit()

    @_locked
    def deaths(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM deaths ORDER BY tick").fetchall()
        return [dict(r) for r in rows]
