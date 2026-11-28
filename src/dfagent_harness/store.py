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
    -- Per-dwarf columns (2026-11-27, diary per-dwarf feed): the
    -- observation already collects these (units.lua) but the
    -- recorder dropped them, so the diary could never see the
    -- dwarves. name: the dwarf's name (so a dead dwarf is still
    -- nameable from their last sample). profession: the dwarf's
    -- profession (so the feed can say "Olon, a brewer" — a person,
    -- not just a name). mood: raw df.mood_type (-1 = none).
    -- mood_name: the enum name ('none' when -1).
    -- stress_category: raw getStressCategory int (0 = most
    -- stressed, 6 = least; -1 = unknown). needs_json: [{need,
    -- level, focus}]. relations_json: [{type, name, histfig_id,
    -- unit_id, in_fort, strength}].
    name TEXT NOT NULL DEFAULT '',
    profession TEXT NOT NULL DEFAULT '',
    mood INTEGER NOT NULL DEFAULT -1,
    mood_name TEXT NOT NULL DEFAULT 'none',
    stress_category INTEGER NOT NULL DEFAULT -1,
    needs_json TEXT NOT NULL DEFAULT '[]',
    relations_json TEXT NOT NULL DEFAULT '[]',
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
        # unit_history gained per-dwarf columns (2026-11-27, diary
        # per-dwarf feed). CREATE TABLE IF NOT EXISTS does not add
        # columns to an existing table, so an existing DB gets them
        # here. Idempotent — a column already present is skipped;
        # old rows keep the column defaults (unknown/empty).
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(unit_history)")}
        for col, ddl in (
                ("name", "TEXT NOT NULL DEFAULT ''"),
                ("profession", "TEXT NOT NULL DEFAULT ''"),
                ("mood", "INTEGER NOT NULL DEFAULT -1"),
                ("mood_name", "TEXT NOT NULL DEFAULT 'none'"),
                ("stress_category", "INTEGER NOT NULL DEFAULT -1"),
                ("needs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("relations_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("social_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("traits_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("emotions_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("goal_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("skills_json", "TEXT NOT NULL DEFAULT '[]'")):
            if col not in cols:
                self.conn.execute(
                    f"ALTER TABLE unit_history ADD COLUMN {col} {ddl}")
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

    @_locked
    def clear_snapshots(self) -> int:
        """Delete all per-section diff baselines. The next snapshot
        renders every section in full. Used at the start of an M1/M2
        run so the model's first observation is the whole fort, not
        "unchanged" one-liners left over from earlier sessions."""
        n = self.conn.execute(
            "SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self.conn.execute("DELETE FROM snapshots")
        self.conn.commit()
        return n

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
                      since_tick: Optional[int] = None,
                      until_tick: Optional[int] = None
                      ) -> list[tuple[int, float]]:
        rows = self.conn.execute(
            "SELECT tick, value FROM trends WHERE metric=? "
            "ORDER BY tick", (metric,)).fetchall()
        out = [(r["tick"], r["value"]) for r in rows]
        if since_tick is not None:
            out = [p for p in out if p[0] >= since_tick]
        if until_tick is not None:
            out = [p for p in out if p[0] <= until_tick]
        return out

    @_locked
    def latest_sample_tick(self) -> Optional[int]:
        """Max tick across EVERY trend metric (or None when no
        sample exists). The daily-sample gate keys on this, not on
        drink alone (2026-11-27, external review Table 4 row 1):
        when the stocks section fails, no drink sample lands and a
        drink-only gate never blocks — unit history rewrites every
        tick, trends grow unbounded, and the per-day diary write
        fires every tick. Any metric landing is proof a sample was
        taken that day."""
        row = self.conn.execute(
            "SELECT MAX(tick) AS m FROM trends").fetchone()
        return row["m"] if row is not None else None

    @_locked
    def clear_trends(self) -> None:
        """Drop every trend sample. Used when the game was reloaded
        to an earlier tick: the old timeline is dead, and its
        samples would corrupt every burn rate (the least-squares
        slope mixes two timelines) and freeze sampling (the day
        number went backwards, so no new sample is ever taken)."""
        self.conn.execute("DELETE FROM trends")
        self.conn.commit()

    @_locked
    def clear_timeline(self) -> None:
        """Drop every time-series record: trends, unit_history and
        deaths. A clock-going-backwards reload kills the whole
        timeline, not just the trends (2026-11-27, external review
        Table 4 row 8): unit_history and deaths from the dead
        timeline would otherwise survive, so post-reload death
        diagnosis reads future samples from a timeline the fort no
        longer has. The snapshot baselines are NOT cleared — they
        are diff state, not history."""
        self.conn.execute("DELETE FROM trends")
        self.conn.execute("DELETE FROM unit_history")
        self.conn.execute("DELETE FROM deaths")
        self.conn.commit()

    @_locked
    def earliest_unit_z(self) -> Optional[int]:
        """Lowest citizen z at the earliest sampled tick (or None
        when nothing was ever sampled). The embark level: on the
        fort's first day every citizen stands at the wagon, so the
        earliest samples pin the ground level the fort started on.
        Used to pin surface_z (2026-11-27, external review Table 5
        row 8): the minimum citizen z drifts down as soon as any
        miner works below the surface, but the embark level never
        moves. Caveat: valid when sampling started at embark (the
        normal case — the daemon samples from the fort's first day);
        a fort whose daemon started mid-game pins whatever its
        first samples saw, which is still no worse than the live
        minimum it replaces."""
        rows = self.conn.execute(
            "SELECT pos_json FROM unit_history "
            "WHERE tick = (SELECT MIN(tick) FROM unit_history)"
            ).fetchall()
        zs = []
        for r in rows:
            try:
                pos = json.loads(r["pos_json"] or "[]")
            except (ValueError, TypeError):
                continue
            if isinstance(pos, list) and len(pos) == 3 \
                    and isinstance(pos[2], int):
                zs.append(pos[2])
        return min(zs) if zs else None

    @_locked
    def burn_rate(self, metric: str, tick: int,
                  days: int = TREND_WINDOW_DAYS) -> Optional[float]:
        """Slope (units per in-game day) over the last ``days`` days.

        Least-squares over the samples in the window. Positive
        means the stock is FALLING (burning). None when fewer than
        two samples or no time span. The window is capped at the
        current tick: samples from a later tick belong to a dead
        timeline (a reload moved the clock backwards) and must not
        pollute the slope.
        """
        since = tick - days * TICKS_PER_DAY
        pts = self.trend_samples(metric, since_tick=since,
                                until_tick=tick)
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
                       days: int = TREND_WINDOW_DAYS,
                       current: Optional[float] = None
                       ) -> Optional[float]:
        """Stock / burn rate, in in-game days. None when the stock
        is not falling, or there is no slope to compute from.

        ``current`` is the stock value RIGHT NOW (the snapshot's
        value). It must be passed by callers that have it — the
        last trend sample is stale by definition (it is from a
        previous day, and after a reload it can be a zero from a
        dead timeline while the real stock is positive, which used
        to print "0.0 days left" and panic the model). When current
        is None the last sample is used. A positive current always
        gives a positive answer; 0.0 is returned only when the
        stock genuinely is 0.
        """
        rate = self.burn_rate(metric, tick, days=days)
        if rate is None or rate <= 0:
            return None
        if current is None:
            pts = self.trend_samples(metric, until_tick=tick)
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
                            wounds: Optional[list] = None,
                            name: str = "",
                            profession: str = "",
                            mood: int = -1,
                            mood_name: str = "none",
                            stress_category: int = -1,
                            needs: Optional[list] = None,
                            relations: Optional[list] = None,
                            social: Optional[list] = None,
                            traits: Optional[list] = None,
                            emotions: Optional[list] = None,
                            goal: Optional[dict] = None,
                            skills: Optional[list] = None) -> None:
        self.conn.execute(
            "INSERT INTO unit_history (unit_id, tick, pos_json, job,"
            " hunger, thirst, sleepiness, stress, wounds_json,"
            " name, profession, mood, mood_name, stress_category,"
            " needs_json, relations_json, social_json, traits_json,"
            " emotions_json, goal_json, skills_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?) "
            "ON CONFLICT(unit_id, tick) DO UPDATE SET "
            "pos_json=excluded.pos_json, job=excluded.job,"
            " hunger=excluded.hunger, thirst=excluded.thirst,"
            " sleepiness=excluded.sleepiness,"
            " stress=excluded.stress,"
            " wounds_json=excluded.wounds_json,"
            " name=excluded.name, profession=excluded.profession,"
            " mood=excluded.mood, mood_name=excluded.mood_name,"
            " stress_category=excluded.stress_category,"
            " needs_json=excluded.needs_json,"
            " relations_json=excluded.relations_json,"
            " social_json=excluded.social_json,"
            " traits_json=excluded.traits_json,"
            " emotions_json=excluded.emotions_json,"
            " goal_json=excluded.goal_json,"
            " skills_json=excluded.skills_json",
            (unit_id, tick, json.dumps(pos or []), job,
             hunger, thirst, sleepiness, stress,
             json.dumps(wounds or []), name, profession, mood,
             mood_name, stress_category, json.dumps(needs or []),
             json.dumps(relations or []),
             json.dumps(social or []),
             json.dumps(traits or []),
             json.dumps(emotions or []),
             json.dumps(goal or {}),
             json.dumps(skills or [])))
        self.conn.commit()

    @_locked
    def unit_ids(self) -> list[int]:
        """Distinct unit ids with any unit_history sample."""
        rows = self.conn.execute(
            "SELECT DISTINCT unit_id FROM unit_history").fetchall()
        return [r[0] for r in rows]

    @_locked
    def earliest_unit_tick(self) -> int | None:
        """The earliest unit_history sample tick, None when the
        Store has never sampled a unit (the fort has not lived a
        sampled day yet)."""
        row = self.conn.execute(
            "SELECT MIN(tick) FROM unit_history").fetchone()
        return row[0] if row and row[0] is not None else None

    @_locked
    def unit_history(self, unit_id: int,
                     limit: Optional[int] = None
                     ) -> list[dict[str, Any]]:
        # A limit means the MOST RECENT N samples (2026-11-27,
        # external review Table 4 row 7): ORDER BY tick with a
        # positive LIMIT used to return the EARLIEST N, the opposite
        # of recent history. Order descending, limit, then reverse
        # so the returned rows are still oldest-first.
        q = ("SELECT * FROM unit_history WHERE unit_id=? "
             "ORDER BY tick DESC")
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
            d["needs"] = json.loads(d.pop("needs_json") or "[]")
            d["relations"] = json.loads(
                d.pop("relations_json") or "[]")
            d["social"] = json.loads(d.pop("social_json") or "[]")
            d["traits"] = json.loads(d.pop("traits_json") or "[]")
            d["emotions"] = json.loads(
                d.pop("emotions_json") or "[]")
            d["goal"] = json.loads(d.pop("goal_json") or "{}")
            d["skills"] = json.loads(d.pop("skills_json") or "[]")
            out.append(d)
        out.reverse()
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
