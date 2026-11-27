#!/usr/bin/env python3
"""M1 driver: tend the fort for one in-game day, driven by a real model.

The model knows NOTHING about Dwarf Fortress. All it gets is the
harness protocol: the per-tick assembled snapshot (GET /v1/snapshot),
the self-describing action catalog (GET /v1/catalog), and the goal
hierarchy below. The driver owns the tick loop; the daemon owns the
game clock only in the sense that the driver advances it in measured
game-tick windows (the daemon's rule-based planner loop is paused
for the run, so the model is the sole decision-maker).

Tick: snapshot -> model -> parse actions -> execute (verified) ->
advance the clock by TICK_WINDOW game ticks -> journal. A failed
model call or a failed action ends the TICK, never the run. The run
ends only when one in-game day (1200 ticks) has elapsed from the
start tick, the fort is dead, a hard error occurs, or a human stops
it. A run ending early because the agent stopped is a harness
failure, not a model failure.

Model route: DeepSeek V4.1 Flash via Free Pi (OpenAI-compatible),
JWT from ~/.free-pi/agent/jwt.txt. Use --mock to drive the loop
with the snapshot's own suggestion instead of a model call (plumbing
test only — never a substitute for a real M1 run).

M1 start procedure (guards added 2026-11-26, after the drink-0
incident — a reload loaded the drink-0 backup and the game ran free
unpaused with no driver):
  1. Reload the save EXPLICITLY, naming it with --exact:
         .venv/bin/python scripts/reload_fort.py \\
             region2-00125-04-01 --exact
     Never use a bare region name for an M1 start while the newest
     backup is a bad state. reload_fort.py verifies the game ends
     paused (GUARD 1) and refuses a save with drink < 10 unless
     --force (GUARD 2, exit 3).
  2. Start the daemon, then pause its loop at once:
         .venv/bin/python scripts/dfh.py daemon --port 8765 \\
             --df-port 5000
         curl -X POST .../v1/control/daemon/pause
     The daemon's pause guard (GUARD 4) re-pauses the game within
     one planner interval if the loop is paused but the game is
     running.
  3. Run the driver. It runs its pre-flight (GUARD 3) before the
     model is consulted: game paused (fresh RPC read), drink >= 10,
     citizens > 0, daemon loop paused. Any failure refuses the run
     (exit 2). On exit — normal, error, or crash — the driver
     re-pauses the game and verifies the pause stuck. It never
     exits with the game running, and never resumes the daemon loop.

Usage:
    .venv/bin/python scripts/m1_driver.py [--days 1] [--window 150]
        [--max-ticks N] [--mock] [--model ID] [--out logs/m1-<ts>.jsonl]
        [--resume]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "src"))

DAEMON_URL = "http://127.0.0.1:8765"
TOKEN_PATH = Path.home() / ".config" / "df-agent-harness" / "token"
JWT_PATH = Path.home() / ".free-pi" / "agent" / "jwt.txt"
FREEPI_BASE = "https://api.freepi.ai"
DEFAULT_MODEL = "deepseek-v4.1-flash"

TICKS_PER_DAY = 1200
DEFAULT_WINDOW = 150  # game ticks advanced per driver tick
MAX_ACTIONS_PER_TICK = 2
STALL_ESCALATE_TICKS = 3   # no actions -> sharper prompt
STALL_FALLBACK_TICKS = 6   # still stalled -> run the suggestion
# GUARD 3 — pre-flight drink floor. A run needs ~5 drink/day (measured
# M1 burn); 10 is ~2 days of headroom. Refuse to start below it.
MIN_DRINK = 10

SYSTEM_PROMPT = """You are the overseer of a Dwarf Fortress fort. You know NOTHING about Dwarf Fortress or its mechanics. Do not use any prior knowledge of the game. Everything you need is in the observation below and the action catalog.

HOW THIS WORKS
- Each turn you receive an observation: the fort's state in plain words, what needs attention, and one suggested action for the single most urgent problem.
- You reply with JSON only: {"reasoning": "<one or two sentences>", "actions": [{"action": "<name>", "kwargs": {...}, "reason": "<why, in game terms>"}]}.
- At most 2 actions per turn. You may also reply with zero actions if nothing needs doing — but a fort always has something to do; an empty turn is suspicious.
- You may also use a "query" action to pull detail the observation only indexes: {"action": "query", "kwargs": {"route": "/v1/column?x=97&y=97"}}. Valid query routes: /v1/slice, /v1/column, /v1/overview, /v1/areas, /v1/area/<id|name>, /v1/path, /v1/survey, /v1/sites?kind=workshop, /v1/unit/<id>, /v1/units, /v1/wiki. The result comes back in your next observation. A query does not count toward the 2-action limit, but do not query when the observation already answers the question. To find a place to build, query /v1/sites?kind=<workshop|stockpile|zone|farm_plot|furniture|trap|room>&w=N&h=N — it returns verified-free sites with their coordinates, and a failed build names a verified alternative to use instead of the blocked site. When you do not know how something works or what to do about an event, look it up in the wiki instead of guessing: {"action": "query", "kwargs": {"route": "/v1/wiki?q=how does brewing work"}}. The briefing lines in the observation already name the wiki pages for the event you are facing — read the full page with /v1/wiki/<slug> when the briefing is not enough.
- The harness executes your actions through the real game and reports what happened (ok or failed, with the cause and the fix). A failed action is information, not a reason to stop: change approach next turn.
- NEVER invent coordinates, ids, or values. Use only what the observation and the catalog give you. If a coordinate is not in the observation, ask for it with a query or use the suggested action's parameters.
- NEVER decide the run is over. The run continues until the harness says so. You decide actions, not whether to keep playing.

PRIORITIES (in order)
1. Survival: no dwarf dies of thirst or hunger. Drink and food come first.
2. Stability: keep dwarves fed, watered, rested, and unstressed; fix what breaks.
3. Growth: only once survival and stability are covered — dig, build, expand.

The catalog below lists every action you can take, with its parameters and legal values. A mistake in a parameter is recoverable: the harness tells you the legal values.
"""


def log_line(path: Path, obj: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


class DaemonClient:
    """HTTP client for the harness daemon (bearer token)."""

    def __init__(self, base: str = DAEMON_URL):
        self.base = base.rstrip("/")
        self.token = TOKEN_PATH.read_text().strip()

    def _req(self, method: str, path: str, body=None,
             timeout: int = 120) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}")

    def get(self, path: str, timeout: int = 120) -> dict:
        return self._req("GET", path, timeout=timeout)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._req("POST", path, body=body or {})

    def snapshot(self) -> dict:
        return self.get("/v1/snapshot", timeout=180)

    def catalog(self) -> dict:
        return self.get("/v1/catalog", timeout=30)

    def units_citizens(self) -> list[dict]:
        """Full citizen records from a fresh collect
        (GET /v1/units?kind=citizens&fresh=1). The poller's cached
        units are the cheap lite records (no needs, wounds list,
        relations, labors, skills, sex, age, goals) — not enough
        for a per-dwarf sample.
        The diary's run-start/run-end samples come from here."""
        res = self.get("/v1/units?kind=citizens&fresh=1", timeout=120)
        units = res.get("units") or []
        return [u for u in units if isinstance(u, dict)]

    def status(self) -> dict:
        return self.get("/v1/status", timeout=15)

    def do_action(self, name: str, kwargs: dict) -> dict:
        return self.post(f"/v1/actions/{name}", kwargs)

    def run_task(self, name: str) -> dict:
        return self.post(f"/v1/tasks/{name}", {})

    def pause_daemon_loop(self) -> dict:
        return self.post("/v1/control/daemon/pause")

    def resume_daemon_loop(self) -> dict:
        return self.post("/v1/control/daemon/resume")

    def daemon_control(self) -> dict:
        return self.get("/v1/control/daemon", timeout=15)

    def set_paused(self, paused: bool) -> dict:
        return self.do_action("pause", {"paused": paused})

    def query(self, route: str) -> dict:
        if not route.startswith("/v1/"):
            raise ValueError(f"query route must start with /v1/: {route!r}")
        # The model writes the route as plain text ("...?q=how does
        # brewing work"), spaces and all. urllib rejects a URL with
        # control characters, so the query string is percent-encoded
        # before the request (run #14: the model's first wiki query
        # died on "URL can't contain control characters"). The path
        # itself is left alone — only the ?query part is encoded.
        if "?" in route:
            from urllib.parse import quote
            path, _, qs = route.partition("?")
            route = path + "?" + quote(qs, safe="=&%")
        return self.get(route, timeout=120)


# FreePiClient lives in the package now (dfagent_harness.freepi)
# so the daemon's diary writer can use the same model.
from dfagent_harness.freepi import FreePiClient  # noqa: E402


def parse_model_reply(text: str) -> tuple[str, list[dict]]:
    """Parse the model's JSON reply. Returns (reasoning, actions)."""
    text = text.strip()
    # Tolerate a fenced code block.
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate prose around the JSON: take the first {...} block.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"model reply is not JSON: {text[:300]}")
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError(f"model reply is not an object: {text[:300]}")
    reasoning = str(data.get("reasoning", ""))[:500]
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("model reply 'actions' is not a list")
    clean = []
    for a in actions:
        if not isinstance(a, dict) or "action" not in a:
            continue
        clean.append({"action": str(a["action"]),
                      "kwargs": a.get("kwargs") or {},
                      "reason": str(a.get("reason", ""))[:300]})
    return reasoning, clean


def parse_suggestion(text: str | None) -> tuple[str, str] | None:
    """Parse the snapshot's free-text suggestion into something the
    driver can run. Returns ("task", name), ("query", route), or
    None when the suggestion names nothing runnable.

    Only the suggestion's PRIMARY action counts: the one the
    leading "Suggested action:" clause names first. A later
    subordinate mention must never be mistaken for the action —
    the still-build suggestion ends "Only then run the brew task.",
    and the old unanchored regex matched that trailing clause and
    drove task:brew on a fort with no still (the mock runs of
    2026-11-27, three times). A suggestion whose primary action is
    a raw action (build a still) or a gathering fix names no
    runnable task/query, so this returns None and the caller takes
    no action — a missed action is visible in the log; a wrong one
    silently drives a dead end.
    """
    if not text:
        return None
    import re
    head = text
    prefix = "Suggested action:"
    if prefix in text:
        head = text.split(prefix, 1)[1]
    head = head.strip()
    m = re.match(r"run the (\w+) task", head)
    if m:
        return ("task", m.group(1))
    m = re.match(r"query unit (\d+)", head)
    if m:
        return ("query", f"/v1/unit/{m.group(1)}")
    return None


def diary_decision_text(name: str, kwargs: dict,
                        workshop_kind: str | None = None
                        ) -> str | None:
    """One model action as a diary decision phrase ("build a Still
    at (95, 108, 175)"). Plain words, not the action name — the
    diary renders "I decided to <phrase>." Every current action is
    mapped here; an unmapped action returns None and the caller
    skips it (a diary phrase must be a clean action phrase — the
    old fallback of "name k=v" leaked raw kwargs into the diary).
    A None return is a signal to add the mapping, not to patch
    around it. ``workshop_kind`` (from the queue_job result
    detail, e.g. "Carpenters") names the workshop the job was
    queued at — the feed groups queued jobs by workshop, and a
    bare "building #7" is not a workshop the diary can name.
    Without it the phrase falls back to "building #N"."""
    kind = str(kwargs.get("kind", ""))
    pos = kwargs.get("pos")
    pos_txt = f" at {tuple(pos)}" if pos else ""
    if name == "build_workshop":
        return f"build a {kind or 'workshop'}{pos_txt}"
    if name == "queue_job":
        count = kwargs.get("count", 1)
        if workshop_kind:
            at = (f"the {workshop_kind} workshop "
                  f"#{kwargs.get('building_id', '?')}")
        else:
            at = f"building #{kwargs.get('building_id', '?')}"
        return (f"queue {kwargs.get('job', 'a job')} "
                f"x{count} at {at}")
    if name == "labor_toggle":
        on = kwargs.get("on", True)
        return (f"{'enable' if on else 'disable'} "
                f"{kwargs.get('labor', 'a labor')} labor on "
                f"{kwargs.get('unit_name', 'a dwarf')}")
    if name == "create_stockpile":
        return (f"create a {kwargs.get('category', 'food')} "
                f"stockpile{pos_txt}")
    if name == "create_zone":
        return (f"create a {kwargs.get('zone_type', 'meeting_area')} "
                f"zone{pos_txt}")
    if name == "designate_gather":
        return "gather plants"
    if name == "designate_chop":
        return "chop trees"
    if name == "designate_dig":
        box = kwargs.get("box") or []
        at = f" at {tuple(box[:3])}" if len(box) >= 3 else ""
        mode = kwargs.get("mode", "")
        if mode in ("", "dig"):
            return f"dig{at}".strip()
        return f"dig a {mode}{at}".strip()
    if name == "dig_to_completion":
        box = kwargs.get("box") or []
        at = f" at {tuple(box[:3])}" if len(box) >= 3 else ""
        return f"dig a {kwargs.get('mode', '')}{at}".strip()
    if name == "build_furniture":
        return f"build {kind or 'furniture'}{pos_txt}"
    if name == "build_farm_plot":
        if not pos_txt and kwargs.get("x") is not None:
            pos_txt = (f" at ({kwargs.get('x')}, "
                       f"{kwargs.get('y')}, {kwargs.get('z')})")
        return f"build a farm plot{pos_txt}"
    if name == "deconstruct_building":
        return (f"deconstruct building "
                f"#{kwargs.get('building_id', '?')}")
    if name == "manager_order_create":
        return (f"order {kwargs.get('job_type', 'an order')} "
                f"x{kwargs.get('amount', 1)} from the manager")
    if name == "manager_order_remove":
        return (f"remove manager order "
                f"#{kwargs.get('order_id', '?')}")
    if name.startswith("task:"):
        return f"run the {name[len('task:'):]} task"
    return None


def decision_phrase_from_log(rec: dict) -> str | None:
    """A log action record's diary phrase, for the retry path.
    Prefers the phrase the driver logged (future logs carry it);
    a log without one rebuilds from params; a queue_job with
    neither rebuilds from the result reason ("queued make_barrel
    x4 on building #7 (jobs [89, 90, 91, 92])"), because the
    bare-params rebuild loses the job, the count, and the
    workshop and renders every queue_job as the same degenerate
    "queue a job x1 at building #?" (run 064517: four different
    jobs deduped to one beat, entry wrote "queued a single
    job"). The kind name is lost in that fallback — the building
    number is the grouping key, and the live path still names
    the workshop."""
    phrase = rec.get("phrase")
    if isinstance(phrase, str) and phrase:
        return phrase
    name = rec.get("name", "")
    params = rec.get("params") or {}
    if name == "queue_job" and not params:
        import re as _re
        m = _re.search(r"queued (\S+) x(\d+) on building #(\d+)",
                       str(rec.get("reason") or ""))
        if m:
            job, count, bid = m.groups()
            return f"queue {job} x{count} at building #{bid}"
    return diary_decision_text(name, params)


def parse_snapshot_stocks(sections: dict | None) -> dict:
    """Start/end stocks from a snapshot's sections (the diary's
    opening/closing numbers). The sections carry the numbers in
    both forms — the full "Stocks: drink 35, food 32, ..." line and
    the diffed "stocks: unchanged (drink 35, ...)" one-liner — so
    one regex covers both. Population comes from the status section
    the same way. Missing values stay None (never guessed)."""
    import re as _re
    out: dict = {}
    if not sections:
        return out
    stocks = str((sections or {}).get("stocks", ""))
    m = _re.search(r"drink (\d+), food (\d+), wood (\d+), "
                   r"stone (\d+)", stocks)
    if m:
        for key, val in zip(("drink", "food", "wood", "stone"),
                            m.groups()):
            out[key] = int(val)
    status = str((sections or {}).get("status", ""))
    m = _re.search(r"(\d+) citizens", status)
    if m:
        out["population"] = int(m.group(1))
    return out


def parse_snapshot_stocks_text(text: str) -> dict:
    """Stocks from a snapshot's rendered text. The run log's
    snapshot records carry only the text (no sections), so the
    retry path cannot use parse_snapshot_stocks — it posted {}
    and the feed fell back to a stale trend sample for the
    opening number (run 064517: the retry's entry said "drink
    down to 33 from 39" when the live run-start number was 38).
    Same regexes as parse_snapshot_stocks, applied to the
    'Stocks: drink 38, food 32, wood 124, stone 0, ...' line
    and the 'N citizens' line. Missing values stay absent
    (never guessed)."""
    import re as _re
    out: dict = {}
    if not text:
        return out
    m = _re.search(r"drink (\d+), food (\d+), wood (\d+), "
                   r"stone (\d+)", text)
    if m:
        for key, val in zip(("drink", "food", "wood", "stone"),
                            m.groups()):
            out[key] = int(val)
    m = _re.search(r"(\d+) citizens", text)
    if m:
        out["population"] = int(m.group(1))
    return out


def parse_fort_name(snap: dict | None) -> str:
    """The fort name from a snapshot ("Erushtathtat, 125-04-02 ..."
    in the header line, or "header: unchanged (Erushtathtat,
    125-04-02)." when diffed). Empty when it cannot be found."""
    import re as _re
    if not snap:
        return ""
    text = str(snap.get("text", "")) or str(
        (snap.get("sections") or {}).get("header", ""))
    m = _re.search(r"([A-Z][\w ]*?),\s*\d+-\d+-\d+", text)
    return m.group(1).strip() if m else ""


def _snapshot_citizens(snap: dict | None) -> list[dict]:
    """The citizen records from a snapshot's units section
    (sections['units']['citizens']), for the diary feed's
    per-dwarf samples. [] when the snapshot carries none (the
    units section may be diffed away on a later tick)."""
    if not snap:
        return []
    units = (snap.get("sections") or {}).get("units") or {}
    # A diffed-away section is a STRING ("unchanged ..."), not a
    # dict — .get on it raises AttributeError and killed the diary
    # write at the end of run #15 (the run itself had completed
    # the day). A non-dict units section carries no citizens.
    if not isinstance(units, dict):
        return []
    citizens = units.get("citizens") or []
    return [c for c in citizens if isinstance(c, dict)]


class M1Driver:
    def __init__(self, args):
        self.args = args
        self.daemon = DaemonClient()
        self.model = None if args.mock else FreePiClient(args.model)
        self.out = Path(args.out)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.start_tick: int | None = None
        self.end_tick: int | None = None
        self.tick_no = 0
        self.stall_ticks = 0
        self.consecutive_model_failures = 0
        self.query_results: list[str] = []
        self.catalog_text: str | None = None
        self.actions_taken = 0
        self.idle_ticks = 0
        # The run's own record for the diary (POST /v1/control/diary
        # at day-complete run end): the model's decisions in order,
        # each with its reason and outcome, plus the start snapshot
        # (for the day's opening stocks + fort name). The daemon's
        # planner loop is paused during M1 runs, so these decisions
        # are not in the Journal and no trend samples are taken for
        # the run's day — without this record the diary entry would
        # say 'a quiet day' for a day the model acted on.
        self.diary_decisions: list[dict] = []
        self.snap0: dict | None = None
        # The run-start citizens from a fresh full collect (fetched
        # in run() once pre-flight passes, while the game is paused).
        # The snapshot's units section is usually diffed away by run
        # end, and snap0's can be stale — the fresh collect is the
        # diary feed's run-start per-dwarf sample. None until fetched.
        self.citizens_start_fresh: list[dict] | None = None
        # Outcomes of the previous tick's actions, fed back to the
        # model in the next prompt so it learns from failures (a
        # wrong action name, a missing parameter, a verification
        # failure) instead of repeating them blind.
        self.last_action_results: list[str] = []
        # Calibrated game-tick rate (ticks per wall second), used by
        # _advance_clock. Starts at a measured-typical 200/s and is
        # re-estimated from every window actually run. The old
        # initial value (50/s) was far below the real rate
        # (~265-350/s on this fort), so the FIRST window overshot
        # ~10x and M1 run #9 ended after a single action tick
        # (100800 -> 102392 for a 150-tick window). The cap was
        # raised to 400, then to 1000: M1 run #11 advanced ~409
        # ticks per 150-tick window, so the real rate on this fort
        # is ~550/s and a 400 cap can never learn it. The minimum
        # sleep is 0.25 s (was 0.5 s) — at 550/s a 0.5 s floor alone
        # is a ~275-tick window.
        self._tick_rate = 400.0

    def _log(self, kind: str, **fields) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(),
               "tick_no": self.tick_no, "kind": kind, **fields}
        log_line(self.out, rec)
        print(f"[m1 tick {self.tick_no} {kind}] "
              + json.dumps(fields)[:300], flush=True)

    def _fetch_fresh_citizens(self, when: str) -> list[dict]:
        """Full citizen records from a fresh collect, for the diary
        feed's per-dwarf samples. Best-effort: a failed fetch logs
        and returns [] (the caller falls back to the snapshot's
        citizens, which are usually empty when the units section is
        diffed away). Never raises — a diary sample must not fail
        the run."""
        try:
            citizens = self.daemon.units_citizens()
        except Exception as exc:  # noqa: BLE001 - best-effort
            self._log("diary_citizens", when=when, error=str(exc)[:200])
            return []
        self._log("diary_citizens", when=when, count=len(citizens))
        return citizens

    def _write_diary(self, snap: dict) -> None:
        """Write the diary entry for the completed day (POST
        /v1/control/diary). The daemon's planner loop is paused
        during M1 runs, so its day-boundary trigger never fires —
        without this call no diary.md entry is ever written for an
        M1 day (2026-11-27: zero entries existed). Best-effort: a
        failed diary write is logged, never fatal to the run. Mock
        runs skip it (their decisions are the harness's, not the
        model's)."""
        if self.args.mock:
            self._log("diary", skipped="mock run")
            return
        if self.start_tick is None:
            self._log("diary", error="no start tick recorded")
            return
        date = (self.snap0 or {}).get("date") or ""
        try:
            year = int(str(date).split("-")[0])
        except (ValueError, IndexError):
            year = 0
        body = {
            "day_start_tick": (self.start_tick // TICKS_PER_DAY
                               * TICKS_PER_DAY),
            "year": year,
            "fort_name": parse_fort_name(self.snap0),
            "decisions": self.diary_decisions,
            "stocks_start": parse_snapshot_stocks(
                (self.snap0 or {}).get("sections")),
            "stocks_end": parse_snapshot_stocks(
                snap.get("sections")),
            # The run-end citizens and the run-start citizens are
            # the feed's per-dwarf samples: the server records them
            # so the diary feed can diff what changed for each dwarf
            # across the run's day. They come from a fresh full
            # units collect, NOT the snapshot: the final snapshot's
            # units section is usually diffed to a one-liner string
            # ("unchanged ..."), which carries no citizens — and
            # snap0's can be stale from a previous daemon instance.
            # With no samples the feed has no dwarf facts for the
            # day and the AI fills the gap from old entries (run
            # #17: Olon credited as the brewer; the brewer is
            # Mestthos). The snapshot citizens are only a fallback
            # when the fresh fetch fails.
            "citizens": (self._fetch_fresh_citizens("end")
                         or _snapshot_citizens(snap)),
            "citizens_start": (self.citizens_start_fresh
                               if self.citizens_start_fresh is not None
                               else _snapshot_citizens(self.snap0)),
            "tick_start": self.start_tick,
        }
        try:
            res = self.daemon.post("/v1/control/diary", body)
            self._log("diary", ok=res.get("ok"), date=res.get("date"),
                      path=res.get("path"))
        except Exception as exc:
            self._log("diary", error=str(exc)[:300])

    # The catalog cap: the compact catalog (no full docstrings)
    # is ~12K chars for 14 actions. The cap is a safety net, not a
    # target — the catalog is a fixed cost and the prompt budget is
    # enforced by the assembler. If the catalog ever outgrows the
    # cap, whole actions are dropped (never a mid-string cut), and
    # the omitted actions are named so the model can query for them.
    CATALOG_MAX_CHARS = 20000

    def _catalog(self) -> str:
        if self.catalog_text is None:
            cat = self.daemon.catalog()
            # Compact: drop each action's full 'detail' docstring
            # (the 'about' first line + constraints carry the
            # meaning). The full catalog was 16,950 chars and the
            # old code hard-truncated it to 12,000 mid-JSON — the
            # model received unclosed JSON cut off mid-word on
            # every tick (2026-11-27 review).
            for a in cat.get("actions", []):
                a.pop("detail", None)
            text = json.dumps(cat, separators=(",", ":"))
            if len(text) > self.CATALOG_MAX_CHARS:
                # Truncate at a JSON boundary: drop whole actions
                # from the end until it fits. Never cut mid-string.
                actions = cat.get("actions", [])
                omitted: list[str] = []
                while (actions and
                       len(text) > self.CATALOG_MAX_CHARS):
                    omitted.append(actions.pop()["name"])
                    text = json.dumps(cat, separators=(",", ":"))
                if omitted:
                    cat["omitted_actions"] = sorted(omitted)
                    cat["omitted_note"] = (
                        "These actions were omitted for size; query "
                        "/v1/catalog for their details.")
                    text = json.dumps(cat, separators=(",", ":"))
            # The catalog the model receives must be valid, closed
            # JSON — verify before caching it.
            json.loads(text)
            self.catalog_text = text
        return self.catalog_text

    def _prompt(self, snap: dict) -> list[dict]:
        snap_text = snap.get("text", "")
        user_parts = [
            f"--- ACTION CATALOG ---\n{self._catalog()}",
            f"--- OBSERVATION (game tick {snap.get('tick')}) ---\n"
            f"{snap_text}"]
        if self.query_results:
            user_parts.append("--- QUERY RESULTS (from your last turn) ---\n"
                              + "\n".join(self.query_results[-3:]))
            self.query_results = []
        if self.last_action_results:
            user_parts.append(
                "--- LAST TURN'S ACTION OUTCOMES ---\n"
                + "\n".join(self.last_action_results[-4:]))
            self.last_action_results = []
        if self.stall_ticks >= STALL_ESCALATE_TICKS:
            user_parts.append(
                "--- ESCALATION ---\n"
                f"You have returned no actions for {self.stall_ticks} "
                "turns in a row. That is not acceptable: a fort always "
                "has something to do. Look at the observation's "
                "suggestion — it names the single most urgent problem "
                "and the exact action to take. Do that action now, "
                "with the parameters the suggestion gives.")
        return [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user_parts)}]

    def _preflight(self, snap: dict) -> list[str]:
        """GUARD 3 — pre-flight check. Before a run starts, verify:
        game paused, drink >= MIN_DRINK, citizens > 0, daemon loop
        paused. Returns the list of failures (empty = pass). A run
        must never start on a drink-0 or running fort (2026-11-26:
        the game ran free unpaused on drink 0 with no driver)."""
        failures: list[str] = []
        status = snap.get("sections") or {}
        status_text = status.get("status", "")
        # Paused: fresh RPC read via GET /v1/pause. The snapshot
        # cannot answer this — paused_read restores the entry pause
        # state after the collect — and /v1/status is the poller's
        # cached state, which only updates while paused. Both would
        # lie about a running game.
        try:
            paused = self.daemon.get("/v1/pause",
                                     timeout=15).get("paused")
        except Exception as exc:
            failures.append(f"pause flag unreadable: {exc}")
            paused = None
        if paused is not True:
            failures.append(f"game not paused (paused={paused})")
        # Drink and citizens come from the snapshot sections. The
        # stocks section is rendered text; parse the drink units out
        # of it, and the citizen count out of the status text.
        import re as _re
        stocks_text = status.get("stocks", "")
        m = _re.search(r"drink[^0-9]*(\d+)", stocks_text, _re.I)
        drink = int(m.group(1)) if m else None
        if drink is None:
            # Fall back to the status route's drink figure.
            try:
                drink = self.daemon.status().get("drink")
            except Exception:
                drink = None
        if drink is None:
            failures.append("drink unreadable")
        elif drink < MIN_DRINK:
            failures.append(
                f"drink {drink} < {MIN_DRINK} floor")
        m = _re.search(r"(\d+) citizens", status_text)
        citizens = int(m.group(1)) if m else None
        if citizens is None:
            try:
                citizens = self.daemon.status().get("population")
            except Exception:
                citizens = None
        if not citizens:
            failures.append(f"citizens {citizens} (fort dead/empty)")
        try:
            loop_paused = self.daemon.daemon_control().get("loop_paused")
        except Exception as exc:
            failures.append(f"daemon loop state unreadable: {exc}")
            loop_paused = None
        if loop_paused is not True:
            failures.append(f"daemon loop not paused "
                            f"(loop_paused={loop_paused})")
        return failures

    def _model_decide(self, snap: dict) -> tuple[str, list[dict]]:
        if self.args.mock:
            # Plumbing test only: run the snapshot's suggestion (a
            # task or a query), never a raw action. If there is no
            # suggestion, take no action.
            parsed = parse_suggestion(snap.get("suggestion"))
            if parsed is None:
                return "mock: no suggestion", []
            kind, name = parsed
            if kind == "task":
                return "mock: suggestion task", [
                    {"action": f"task:{name}", "kwargs": {},
                     "reason": "mock suggestion"}]
            return "mock: suggestion query", [
                {"action": "query", "kwargs": {"route": name},
                 "reason": "mock suggestion"}]
        text = self.model.chat(self._prompt(snap))
        return parse_model_reply(text)

    def _advance_clock(self, target_tick: int, current_tick: int) -> int:
        """Unpause for a wall-clock estimate of the window, re-pause,
        and read the tick reached. Returns the tick reached.

        The advance is ONE server-side call (POST
        /v1/control/advance-clock) that holds the daemon's RPC lock
        across the whole unpause — no other thread can make an RPC
        call while the game is running. The old three-call advance
        (unpause, sleep client-side, re-pause) left the unpause
        window open, and the poller/guard's RFR reads landing in
        it crashed DF twice (runs #12/#13, double-free abort in
        the DFHack RPC server).

        Windows are measured in game ticks, but the tick CANNOT be
        read while the game is running: /v1/status returns the
        poller's cached last_state, and the poller only collects
        while the game is already paused (read safety, world-model
        design §8). Polling /v1/status during the window therefore
        returns the stale pre-unpause tick forever and the loop
        waits the whole deadline — that is what ran the fort 19
        in-game days and hit drink 0 on 2026-11-26. So: estimate
        the wall time from a calibrated tick rate, advance, and
        read the tick from the endpoint's response.
        """
        window = target_tick - current_tick
        if window <= 0:
            return current_tick
        sleep_s = window / self._tick_rate
        sleep_s = max(0.25, min(sleep_s, 30.0))
        res = self.daemon.post("/v1/control/advance-clock",
                               {"sleep_s": sleep_s})
        advanced = res.get("advanced", 0)
        reached = res.get("tick_after", current_tick)
        if not isinstance(reached, int):
            reached = current_tick
        # Calibrate the tick rate on the UNPAUSED span, not the
        # sleep: the set_paused round trips run while the game
        # ticks, so advanced / sleep_s overstates the rate (run
        # #12's first window: 803 ticks for a 150 target, rate
        # read as 2141/s and capped at 1000). The server returns
        # unpaused_s; older servers lack it — fall back to sleep_s.
        # Every advance is logged (sleep, unpaused span, ticks,
        # rate) so a run-log review can verify the accounting
        # instead of inferring it from snapshot ticks.
        unpaused_s = res.get("unpaused_s")
        if not isinstance(unpaused_s, (int, float)) \
                or unpaused_s <= 0:
            unpaused_s = sleep_s
        if isinstance(advanced, int) and advanced > 0 \
                and unpaused_s > 0:
            rate = advanced / unpaused_s
            self._tick_rate = max(10.0, min(1000.0, rate))
        self._log("clock_advance", sleep_s=round(sleep_s, 3),
                  unpaused_s=round(unpaused_s, 3),
                  tick_before=current_tick, tick_after=reached,
                  advanced=advanced if isinstance(advanced, int)
                  else None,
                  rate=round(self._tick_rate, 1))
        if not isinstance(advanced, int) or advanced <= 0:
            # The clock did not move during the window. A modal
            # dialog freezes the tick even when the pause flag is
            # clear — run the advance check (POST /v1/control/
            # advance): it dismisses a blocking screen
            # programmatically (per the allowlist) or names the
            # blocking screen as a failure, so a modal can never
            # stall a run silently.
            try:
                res = self.daemon.post("/v1/control/advance", {})
                self._log("advance", result=res)
                print(f"m1: advance check: {res}", flush=True)
            except Exception as exc:
                self._log("advance_error", error=str(exc)[:300])
        return reached

    def run(self) -> int:
        # The daemon loop is paused so the rule-based planner does
        # not also act; the model is the sole decision-maker.
        self.daemon.pause_daemon_loop()
        # Clear the snapshot diff baselines so the model's FIRST
        # observation is the whole fort in full, not "unchanged"
        # one-liners left over from earlier sessions. Later ticks
        # diff normally.
        try:
            from dfagent_harness.store import Store, default_world_db_path
            n = Store(default_world_db_path()).clear_snapshots()
            print(f"m1: cleared {n} snapshot baselines", flush=True)
        except Exception as exc:
            print(f"m1: baseline clear failed (continuing): {exc}",
                  flush=True)
        self._log("run_start", days=self.args.days,
                  window=self.args.window, model=self.args.model,
                  mock=self.args.mock)
        try:
            snap0 = self.daemon.snapshot()
        except Exception as exc:
            self._log("fatal", error=f"first snapshot failed: {exc}")
            return 2
        self.snap0 = snap0
        self.start_tick = snap0.get("tick") or 0
        self.end_tick = self.start_tick + int(self.args.days * TICKS_PER_DAY)
        # snap0 itself stores a fresh baseline, so the tick-1
        # snapshot would diff against it and come back mostly
        # "unchanged" one-liners (the model stalled on exactly that,
        # 2026-11-26). Clear again so tick 1 is full too.
        try:
            from dfagent_harness.store import Store, default_world_db_path
            n = Store(default_world_db_path()).clear_snapshots()
            print(f"m1: cleared {n} snapshot baselines (post-snap0)",
                  flush=True)
        except Exception as exc:
            print(f"m1: post-snap0 baseline clear failed "
                  f"(continuing): {exc}", flush=True)
        # GUARD 3 — pre-flight. Refuse to start unless the game is
        # paused, drink >= MIN_DRINK, citizens > 0, and the daemon
        # loop is paused. Say which check failed. The game is left
        # paused; the run does not start.
        failures = self._preflight(snap0)
        if failures:
            self._log("preflight_refused", failures=failures)
            print(f"m1: PRE-FLIGHT REFUSED — {'; '.join(failures)}",
                  flush=True)
            return 2
        print("m1: pre-flight OK — game paused, drink >= "
              f"{MIN_DRINK}, citizens > 0, daemon loop paused",
              flush=True)
        # The diary feed's run-start per-dwarf sample: a fresh full
        # units collect now, while the game is paused at the run's
        # start tick. (The snapshot's units section is diffed away
        # by run end, and snap0's can be stale — neither is a
        # reliable sample. See _write_diary.)
        if not self.args.mock:
            self.citizens_start_fresh = self._fetch_fresh_citizens(
                "start")
        self._log("start_tick", start_tick=self.start_tick,
                  end_tick=self.end_tick,
                  date=snap0.get("date"))
        while True:
            self.tick_no += 1
            if (self.args.max_ticks and
                    self.tick_no > self.args.max_ticks):
                self._log("run_end", reason="max_ticks reached")
                return 0
            try:
                snap = self.daemon.snapshot()
            except Exception as exc:
                self._log("tick_error", error=f"snapshot failed: {exc}")
                time.sleep(5)
                continue
            # The observation is logged in full (snapshot text +
            # suggestion) so a run-log review can verify what the
            # model actually saw — M1 run #11 tick 1 idled on "no
            # verified coordinates" and the logs could not say
            # whether the snapshot really lacked them, because only
            # the model's reasoning was recorded.
            self._log("snapshot", text=snap.get("text", ""),
                      suggestion=snap.get("suggestion"))
            tick = snap.get("tick") or 0
            if tick >= self.end_tick:
                self._log("run_end", reason="day complete",
                          tick=tick, end_tick=self.end_tick,
                          actions_taken=self.actions_taken,
                          idle_ticks=self.idle_ticks)
                self._write_diary(snap)
                return 0
            # Fort dead check: parse the citizen count out of the
            # status section. (A plain substring check for
            # "0 citizens" false-positives on "10 citizens".)
            import re as _re
            status = (snap.get("sections") or {}).get("status", "")
            _m = _re.search(r"(\d+) citizens", status)
            if _m is not None and int(_m.group(1)) == 0:
                self._log("run_end", reason="fort dead", tick=tick)
                return 1
            try:
                reasoning, actions = self._model_decide(snap)
                self.consecutive_model_failures = 0
            except Exception as exc:
                self.consecutive_model_failures += 1
                self._log("model_failure",
                          error=str(exc)[:300],
                          consecutive=self.consecutive_model_failures)
                if self.consecutive_model_failures >= 5:
                    self._log("run_end",
                              reason="model failed 5 ticks in a row")
                    return 2
                # A failed model call ends the TICK, not the run:
                # advance the clock a little and try again.
                try:
                    self._advance_clock(tick + self.args.window, tick)
                except Exception as exc:
                    # DF died mid-run (observed 2026-11-26: the
                    # driver crashed with an unhandled RuntimeError
                    # from _advance_clock when DF died). A dead game
                    # ends the RUN cleanly (exit 1); the finally in
                    # main() still re-pauses best-effort.
                    self._log("run_end",
                              reason="game unreachable during clock "
                                     f"advance: {exc}")
                    return 1
                continue
            # Split queries from real actions; queries run first and
            # their results join the next prompt.
            real, queries = [], []
            for a in actions:
                (queries if a["action"] == "query" else real).append(a)
            for q in queries[:3]:
                route = (q.get("kwargs") or {}).get("route", "")
                try:
                    res = self.daemon.query(route)
                    self.query_results.append(
                        f"{route} -> {json.dumps(res)[:2000]}")
                    self._log("query", route=route,
                              result=json.dumps(res)[:2000])
                except Exception as exc:
                    self.query_results.append(
                        f"{route} -> ERROR {exc}"[:500])
                    self._log("query", route=route,
                              error=str(exc)[:300])
            if not real:
                self.stall_ticks += 1
                self.idle_ticks += 1
                self._log("idle_tick", reasoning=reasoning[:200],
                          stall_ticks=self.stall_ticks)
                if self.stall_ticks >= STALL_FALLBACK_TICKS:
                    # Fallback: run the snapshot's suggestion.
                    parsed = parse_suggestion(snap.get("suggestion"))
                    if parsed is not None:
                        kind, name = parsed
                        self._log("fallback", kind=kind, name=name)
                        try:
                            if kind == "task":
                                res = self.daemon.run_task(name)
                            else:
                                res = self.daemon.query(name)
                            self._log("action", name=f"{kind}:{name}",
                                      ok=res.get("ok"),
                                      reason=str(res.get("reason")
                                                 or res.get("detail", ""))[:200])
                            self.last_action_results.append(
                                f"{kind}:{name} -> "
                                f"{'OK' if res.get('ok') else 'FAILED'}: "
                                f"{str(res.get('reason') or res.get('detail', ''))[:200]}")
                            self.actions_taken += 1
                        except Exception as exc:
                            self._log("action_error",
                                      name=f"{kind}:{name}",
                                      error=str(exc)[:300])
                            self.last_action_results.append(
                                f"{kind}:{name} -> ERROR: {str(exc)[:200]}")
                        self.stall_ticks = 0
            else:
                self.stall_ticks = 0
                for a in real[:MAX_ACTIONS_PER_TICK]:
                    try:
                        if a["action"].startswith("task:"):
                            res = self.daemon.run_task(
                                a["action"][len("task:"):])
                        else:
                            res = self.daemon.do_action(
                                a["action"], a.get("kwargs") or {})
                        # The run's diary record: the model's
                        # decisions in order, with reason + outcome.
                        # The daemon's Journal never sees M1 actions
                        # (its loop is paused), so without this the
                        # diary entry for the day would be empty.
                        # An action with no clean diary phrase is
                        # skipped here (logged, so the mapping gap
                        # is visible) rather than rendered as raw
                        # name + kwargs. The phrase is computed
                        # BEFORE the log below, so the log record
                        # carries it: a retry rebuilds the day's
                        # decisions from the log, and rebuilding
                        # from bare params lost the job, the count,
                        # and the workshop — four different queue_job
                        # actions all rendered as "queue a job x1
                        # at building #?", deduped to one beat, and
                        # the entry wrote "queued a single job"
                        # (run 064517).
                        phrase = diary_decision_text(
                            a["action"], a.get("kwargs") or {},
                            workshop_kind=(
                                (res.get("detail") or {}).get(
                                    "building_kind")
                                if a["action"] == "queue_job"
                                else None))
                        self._log("action", name=a["action"],
                                  ok=res.get("ok"),
                                  reason=str(res.get("reason"))[:300],
                                  model_reason=a.get("reason", "")[:200],
                                  params=a.get("kwargs") or {},
                                  phrase=phrase)
                        if phrase is None:
                            self._log("diary_no_phrase",
                                      name=a["action"])
                        else:
                            self.diary_decisions.append({
                                "decision": phrase,
                                "reason": a.get("reason", ""),
                                "action": a["action"],
                                "ok": bool(res.get("ok")),
                                "result": str(res.get("reason") or "")[:300],
                            })
                        self.last_action_results.append(
                            f"{a['action']} -> "
                            f"{'OK' if res.get('ok') else 'FAILED'}: "
                            f"{str(res.get('reason') or res.get('detail', '') or res.get('fix', ''))[:250]}")
                        self.actions_taken += 1
                    except Exception as exc:
                        self._log("action_error", name=a["action"],
                                  error=str(exc)[:300])
                        self.last_action_results.append(
                            f"{a['action']} -> ERROR: {str(exc)[:250]}")
            try:
                self._advance_clock(tick + self.args.window, tick)
            except Exception as exc:
                # Same as the model-failure branch above: a DF death
                # ends the run cleanly, never crashes the driver.
                self._log("run_end",
                          reason="game unreachable during clock "
                                 f"advance: {exc}")
                return 1
        # unreachable
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=1.0)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--max-ticks", type=int, default=0)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.out is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        args.out = str(HARNESS / "logs" / f"m1-{ts}.jsonl")
    if not args.mock and not JWT_PATH.exists():
        print(f"m1: no JWT at {JWT_PATH} — run the Free Pi device "
              "flow first", file=sys.stderr)
        return 2
    if not TOKEN_PATH.exists():
        print(f"m1: no daemon token at {TOKEN_PATH} — start the "
              "daemon first (dfh start)", file=sys.stderr)
        return 2
    driver = M1Driver(args)
    rc = 1
    try:
        rc = driver.run()
    finally:
        # Do NOT resume the daemon loop and do NOT leave the game
        # running. An unattended run burns drink fast: on 2026-11-26
        # a mock run's exit resumed the loop and the fort ran 19
        # in-game days to drink 0 before anyone noticed. Leave the
        # game paused and the loop paused; the parent decides when
        # to resume. GUARD 3 — verify the pause stuck (read it back
        # via GET /v1/pause); retry once if it did not.
        paused_ok = False
        for attempt in range(2):
            try:
                driver.daemon.set_paused(True)
                paused = driver.daemon.get("/v1/pause",
                                           timeout=15).get("paused")
                if paused is True:
                    paused_ok = True
                    break
            except Exception:
                pass
        if paused_ok:
            print("m1: exit — game verified PAUSED", flush=True)
        else:
            print("m1: exit — WARNING: pause could not be verified; "
                  "the game may still be running", flush=True)
        # Persist the run's progress. DF dies often (the
        # Resetting-textures abort) and every death wipes the
        # in-memory progress — runs #9/#10 built a still and a
        # stockpile, then a death reloaded the clean 04-01 state
        # and the model had to rebuild them. A successful run end
        # (day complete / max_ticks) saves the fort so the next run
        # starts from the progressed state, not from 04-01. Only
        # on rc 0: a dead or refused run must not overwrite the
        # good save with a bad state. Best-effort — a failed save
        # never changes the exit code.
        if rc == 0 and paused_ok:
            try:
                driver.daemon.post("/v1/control/quicksave", {})
                print("m1: exit — quicksave requested (progress "
                      "persisted)", flush=True)
            except Exception as exc:  # noqa: BLE001 - best-effort
                print(f"m1: exit — WARNING: quicksave failed: {exc}",
                      flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
