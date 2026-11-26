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
- You may also use a "query" action to pull detail the observation only indexes: {"action": "query", "kwargs": {"route": "/v1/column?x=97&y=97"}}. Valid query routes: /v1/slice, /v1/column, /v1/overview, /v1/areas, /v1/area/<id|name>, /v1/path, /v1/survey, /v1/unit/<id>, /v1/units, /v1/wiki. The result comes back in your next observation. A query does not count toward the 2-action limit, but do not query when the observation already answers the question.
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
        return self.get(route, timeout=120)


class FreePiClient:
    """OpenAI-compatible chat completions via Free Pi."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.base = FREEPI_BASE
        self.token = JWT_PATH.read_text().strip()

    def chat(self, messages: list[dict], timeout: int = 180) -> str:
        body = {"model": self.model, "messages": messages,
                "temperature": 0.2}
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {self.token}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            raise RuntimeError(
                f"Free Pi chat -> HTTP {e.code}: {detail}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Free Pi chat: no choices in {data}")
        return choices[0]["message"]["content"]

    def list_models(self) -> list[str]:
        # Free Pi exposes no /models endpoint (404 on /models,
        # /v1/models, /api/models — verified 2026-11-26). The known
        # model ids, verified live via chat completions (the response
        # 'model' field is authoritative; the model's self-reported
        # identity is not — DeepSeek models claim to be GPT-4.1 /
        # Claude, a known training-data artifact):
        #   deepseek-v4.1-flash -> deepseek-v4.1-flash-1017
        #   particle            -> deepseek-v4-flash-0731 (+ LoRA)
        return ["deepseek-v4.1-flash", "deepseek-v4-flash", "particle"]


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
    None when the suggestion names nothing runnable. The suggestion
    is prose ("Suggested action: run the brew task (POST
    /v1/tasks/brew) — ..."), so this matches its known shapes
    rather than pretending it is structured."""
    if not text:
        return None
    import re
    m = re.search(r"run the (\w+) task", text)
    if m:
        return ("task", m.group(1))
    m = re.search(r"query unit (\d+)", text)
    if m:
        return ("query", f"/v1/unit/{m.group(1)}")
    return None


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
        # Outcomes of the previous tick's actions, fed back to the
        # model in the next prompt so it learns from failures (a
        # wrong action name, a missing parameter, a verification
        # failure) instead of repeating them blind.
        self.last_action_results: list[str] = []
        # Calibrated game-tick rate (ticks per wall second), used by
        # _advance_clock. Starts at a measured-typical 50/s and is
        # re-estimated from every window actually run.
        self._tick_rate = 50.0

    def _log(self, kind: str, **fields) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(),
               "tick_no": self.tick_no, "kind": kind, **fields}
        log_line(self.out, rec)
        print(f"[m1 tick {self.tick_no} {kind}] "
              + json.dumps(fields)[:300], flush=True)

    def _catalog(self) -> str:
        if self.catalog_text is None:
            cat = self.daemon.catalog()
            # The catalog route returns the whole catalog + how_to_call.
            text = json.dumps(cat)[:12000]
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

        Windows are measured in game ticks, but the tick CANNOT be
        read while the game is running: /v1/status returns the
        poller's cached last_state, and the poller only collects
        while the game is already paused (read safety, world-model
        design §8). Polling /v1/status during the window therefore
        returns the stale pre-unpause tick forever and the loop
        waits the whole deadline — that is what ran the fort 19
        in-game days and hit drink 0 on 2026-11-26. So: estimate
        the wall time from a calibrated tick rate, sleep, re-pause,
        then read the tick from /v1/status (which refreshes within
        ~6 s once paused) and re-calibrate the rate from the
        observed advance.
        """
        window = target_tick - current_tick
        if window <= 0:
            return current_tick
        sleep_s = window / self._tick_rate
        sleep_s = max(0.5, min(sleep_s, 30.0))
        t_unpause = time.time()
        self.daemon.set_paused(False)
        time.sleep(sleep_s)
        self.daemon.set_paused(True)
        unpause_s = time.time() - t_unpause
        reached = current_tick
        deadline = time.time() + 10.0
        while time.time() < deadline:
            st = self.daemon.status()
            tick = st.get("tick")
            if isinstance(tick, int) and tick != current_tick:
                reached = tick
                break
            time.sleep(0.5)
        # Calibrate the tick rate from the UNPAUSE duration only:
        # the status-poll wait after re-pausing runs while the game
        # is paused, so counting it would understate the rate.
        advanced = reached - current_tick
        if unpause_s > 0 and advanced > 0:
            rate = advanced / unpause_s
            self._tick_rate = max(10.0, min(200.0, rate))
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
        self._log("start_tick", start_tick=self.start_tick,
                  end_tick=self.end_tick,
                  date=(snap0.get("sections") or {}).get("status", "")[:80])
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
            tick = snap.get("tick") or 0
            if tick >= self.end_tick:
                self._log("run_end", reason="day complete",
                          tick=tick, end_tick=self.end_tick,
                          actions_taken=self.actions_taken,
                          idle_ticks=self.idle_ticks)
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
                except Exception as exc:
                    self.query_results.append(
                        f"{route} -> ERROR {exc}"[:500])
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
                        self._log("action", name=a["action"],
                                  ok=res.get("ok"),
                                  reason=str(res.get("reason"))[:300],
                                  model_reason=a.get("reason", "")[:200])
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
    try:
        return driver.run()
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


if __name__ == "__main__":
    sys.exit(main())
