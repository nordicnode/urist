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

    def pause_daemon_loop(self) -> dict:
        return self.post("/v1/control/daemon/pause")

    def resume_daemon_loop(self) -> dict:
        return self.post("/v1/control/daemon/resume")

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

    def _model_decide(self, snap: dict) -> tuple[str, list[dict]]:
        if self.args.mock:
            sugg = snap.get("suggestion") or {}
            act = sugg.get("action")
            if not act:
                return "mock: no suggestion", []
            return "mock: using suggestion", [
                {"action": act, "kwargs": sugg.get("kwargs") or {},
                 "reason": sugg.get("reason", "suggestion")}]
        text = self.model.chat(self._prompt(snap))
        return parse_model_reply(text)

    def _advance_clock(self, target_tick: int) -> int:
        """Unpause, wait until year_tick >= target, re-pause. Returns
        the tick reached. Windows are measured in game ticks."""
        self.daemon.set_paused(False)
        deadline = time.time() + 120
        reached = None
        while time.time() < deadline:
            st = self.daemon.status()
            tick = ((st.get("status") or {}).get("year_tick")
                    or (st.get("tick")))
            if isinstance(tick, int):
                reached = tick
                if tick >= target_tick:
                    break
            time.sleep(0.5)
        self.daemon.set_paused(True)
        return reached if reached is not None else target_tick

    def run(self) -> int:
        # The daemon loop is paused so the rule-based planner does
        # not also act; the model is the sole decision-maker.
        self.daemon.pause_daemon_loop()
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
            # Fort dead check: population 0.
            status = (snap.get("sections") or {}).get("status", "")
            if "0 citizens" in status or "population 0" in status:
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
                self._advance_clock(tick + self.args.window)
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
                    sugg = snap.get("suggestion") or {}
                    if sugg.get("action"):
                        self._log("fallback",
                                  action=sugg.get("action"))
                        try:
                            res = self.daemon.do_action(
                                sugg["action"], sugg.get("kwargs") or {})
                            self._log("action", name=sugg["action"],
                                      ok=res.get("ok"),
                                      reason=str(res.get("reason"))[:200])
                            self.actions_taken += 1
                        except Exception as exc:
                            self._log("action_error",
                                      name=sugg.get("action"),
                                      error=str(exc)[:300])
                        self.stall_ticks = 0
            else:
                self.stall_ticks = 0
                for a in real[:MAX_ACTIONS_PER_TICK]:
                    try:
                        res = self.daemon.do_action(
                            a["action"], a.get("kwargs") or {})
                        self._log("action", name=a["action"],
                                  ok=res.get("ok"),
                                  reason=str(res.get("reason"))[:300],
                                  model_reason=a.get("reason", "")[:200])
                        self.actions_taken += 1
                    except Exception as exc:
                        self._log("action_error", name=a["action"],
                                  error=str(exc)[:300])
            self._advance_clock(tick + self.args.window)
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
        # Leave the daemon loop resumed so the fort is tended by the
        # rule-based planner after the run.
        try:
            driver.daemon.resume_daemon_loop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
