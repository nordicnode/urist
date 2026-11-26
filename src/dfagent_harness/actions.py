"""Verified action layer for the DF Agent Harness (phase 2).

Every action follows the same contract: read the world state **before**,
execute the mutation, then read the world state **after** through the
observation layer and check the postcondition. A success means "verified
in the game", never "command sent". On any failure the action stops at
the first failure with an honest blocking reason; there are no retries
anywhere in this module — a caller that wants to retry must re-read state
first and call :func:`act` again with fresh eyes.

Transport
---------
Mutations and targeted read-backs run as Lua helpers (``lua/act_*.lua``,
``lua/probe_*.lua``) over the existing :mod:`dfhack_rpc` transport via
``RunCommand("lua", ...)`` — the proven path from phase 1 — with one
exception: pause/unpause uses RFR ``GetPauseState``/``SetPauseState``,
because phase 1 verified that those stick (PROTOCOL.md §8). No other RFR
method offered a better call for the actions below: RFR has no
designation, order, labor or building API, and its ``SendDigCommand``
only covers the dig modes the Lua path already handles with a precise
read-back. The Lua helpers are written from scratch; their mechanisms
are documented per action in ``docs/ACTIONS.md`` and in each helper's
header comment.

Read-back
--------
Targeted probes (``probe_dig``, ``probe_plants``, ``probe_jobs_at``,
``probe_material``, ``probe_site``) read the same structs the game uses,
so a probe count is the state as the game sees it. Where a full observe
section is cheap and is the natural read-back (manager orders, buildings,
labors), the action uses :func:`dfagent_harness.observe.collect` for
that section instead of a new probe. See :func:`_read_section`.

Error model
-----------
``ActionResult.error_kind`` is one of:

* ``None`` — the action succeeded and its effect was observed.
* ``"precondition"`` — the action refused to run: the world was not in
  a state where the action could work (no trees in the area, no
  accessible material, site occupied, unknown name). Nothing was written.
* ``"transport"`` — the RPC call failed or the read-back was unavailable,
  so the outcome is *unknown*. The caller must re-read state before
  deciding anything; it must never assume the mutation did or did not
  happen.
* ``"verification"`` — the mutation ran but the effect was not observed
  on re-read (or the game rejected it, e.g. a construction job cancelled).
* ``"timeout"`` — an async effect (workshop construction, job spawn) did
  not appear within its bounded wait. The mutation itself may have taken
  effect; the caller must re-read state.

The daemon (phase 4) will call :func:`act`; see ``docs/ACTIONS.md``.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from dfhack_rpc import DFHackClient, DFHackError
from dfhack_rpc.proto import CoreProtocol_pb2 as core
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr

from . import observe

__all__ = [
    "ActionResult",
    "ACTIONS",
    "DIG_MODES",
    "WORKSHOP_CATALOG",
    "act",
    "designate_dig",
    "designate_chop",
    "designate_gather",
    "manager_order_create",
    "manager_order_remove",
    "build_workshop",
    "labor_toggle",
    "get_paused",
    "set_paused",
]

_LUA_DIR = Path(__file__).resolve().parent / "lua"

#: CLI dig mode -> df.tile_dig_designation enum name ('clear' is special).
DIG_MODES: dict[str, str] = {
    "dig": "Default",
    "channel": "Channel",
    "ramp": "Ramp",
    "up-stair": "UpStair",
    "down-stair": "DownStair",
    "up-down-stair": "UpDownStair",
    "clear": "clear",
}

#: Workshop kind -> building definition. ``material`` is the df.item_type
#: whose accessible stock the precondition checks (see probe_material).
WORKSHOP_CATALOG: dict[str, dict[str, Any]] = {
    "carpenter": {"type": "Workshop", "subtype": "Carpenters",
                  "width": 3, "height": 3, "material": "WOOD"},
    "mason": {"type": "Workshop", "subtype": "Masons",
              "width": 3, "height": 3, "material": "BOULDER"},
    "still": {"type": "Workshop", "subtype": "Still",
              "width": 3, "height": 3, "material": "BOULDER"},
    "kitchen": {"type": "Workshop", "subtype": "Kitchen",
                "width": 3, "height": 3, "material": "BOULDER"},
}

#: Job types the game spawns from a plant designation.
_PLANT_JOBS = {"tree": "FellTree", "shrub": "GatherPlants"}

#: Default bounded waits (seconds) for async effects.
DEFAULT_BUILD_TIMEOUT = 120.0
#: Mark tier-2 (job spawn) and gather-unmark (job removal): the game's
#: designation sweep is slow and variable (a FellTree job took ~2s once,
#: ~6s once, >30s once), so the bound is generous — the wait ends as
#: soon as the job appears/vanishes.
DEFAULT_JOB_TIMEOUT = 60.0


class _Fail(Exception):
    """An action failure with a stable kind and a human reason."""

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


@dataclass
class ActionResult:
    """The result of one verified action (JSON-serialisable via to_dict)."""

    ok: bool
    action: str
    before: Any = None
    after: Any = None
    reason: str = ""
    error_kind: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)
    took_ms: int = 0
    mechanism: str = "lua"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "error_kind": self.error_kind,
            "detail": self.detail,
            "took_ms": self.took_ms,
            "mechanism": self.mechanism,
        }


# -- Lua plumbing ---------------------------------------------------------

def _lua_str(value: str) -> str:
    """Encode a Python str as a Lua string literal.

    DF strings are CP437 bytes (dwarf names carry e.g. 0x84 = 'ä'), so
    encode as CP437 when possible and emit decimal byte escapes; fall
    back to UTF-8 escapes for characters outside CP437.
    """
    try:
        raw = value.encode("cp437")
    except UnicodeEncodeError:
        raw = value.encode("utf-8")
    return '"' + "".join(f"\\{b}" for b in raw) + '"'


def _lua_literal(value: Any) -> str:
    """Encode a small Python value (None/bool/int/float/str/list/dict)."""
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _lua_str(value)
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(_lua_literal(v) for v in value) + "}"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if not isinstance(k, str) or not k.isidentifier():
                raise ValueError(f"bad PARAMS key: {k!r}")
            parts.append(f"{k} = {_lua_literal(v)}")
        return "{" + ", ".join(parts) + "}"
    raise ValueError(f"cannot encode PARAMS value: {value!r}")


def _load_lua(name: str, params: dict[str, Any]) -> str:
    """Shared JSON prelude + PARAMS block + one helper, as one Lua chunk."""
    prelude = (_LUA_DIR / "json.lua").read_text()
    helper = (_LUA_DIR / name).read_text()
    return prelude + "\nPARAMS = " + _lua_literal(params) + "\n" + helper


def _run_helper(client: DFHackClient, name: str,
                params: dict[str, Any],
                timeout: float = 30.0) -> dict[str, Any]:
    """Run one Lua helper; return its parsed JSON object.

    Transport/parse failures raise DFHackError / ValueError — the caller
    maps those to error_kind "transport" (outcome unknown). A helper that
    ran and reports ``ok: false`` returns its dict unchanged.
    """
    code = _load_lua(name, params)
    out = client.run_lua_json(code, timeout=timeout)
    if not isinstance(out, dict):
        raise ValueError(
            f"helper {name} returned non-object JSON: {out!r:.200}")
    return out


def _helper_or_fail(client: DFHackClient, name: str,
                    params: dict[str, Any],
                    timeout: float = 30.0) -> dict[str, Any]:
    """Run a helper; a helper-side ``ok: false`` becomes an :class:`_Fail`.

    The helper's ``kind`` field (when present) is ``"precondition"`` for
    refusals that wrote nothing; anything else is a verification failure.
    """
    out = _run_helper(client, name, params, timeout=timeout)
    if not out.get("ok", False):
        kind = out.get("kind") or "verification"
        if kind not in ("precondition", "verification"):
            kind = "verification"
        error = out.get("error") or f"{name} failed: {out!r:.200}"
        # The helpers refuse unknown input names before writing anything;
        # those are preconditions, not failed effects.
        if kind == "verification" and error.startswith("unknown "):
            kind = "precondition"
        raise _Fail(kind, error)
    return out


# -- pause (RFR — the one non-Lua mechanism) -------------------------------

def get_paused(client: DFHackClient) -> bool:
    """Read the pause flag via RFR GetPauseState."""
    state, _text = client.call("GetPauseState", core.EmptyMessage(),
                               rfr.SingleBool)
    return bool(state.Value)


def set_paused(client: DFHackClient, paused: bool) -> bool:
    """Set the pause flag via RFR SetPauseState; verify by re-reading.

    Returns the verified state. Raises _Fail('verification') when the
    flag does not stick.
    """
    client.call("SetPauseState", rfr.SingleBool(Value=paused),
                core.EmptyMessage)
    actual = get_paused(client)
    if actual != paused:
        raise _Fail("verification",
                    f"pause flag did not stick: wanted {paused}, got {actual}")
    return actual


@contextmanager
def _unpaused_for_ticks(client: DFHackClient) -> Iterator[bool]:
    """Unpause for a bounded wait, then restore the prior pause state.

    Yields True when the game was paused on entry (so it was unpaused by
    us and will be re-paused); yields False when the game was already
    running (left running). Restoration runs even on failure; a restore
    failure is raised as a verification failure (the game is left in a
    known-reported state, never silently running).
    """
    was_paused = get_paused(client)
    if was_paused:
        set_paused(client, False)
    try:
        yield was_paused
    finally:
        if was_paused:
            set_paused(client, True)


def _flag_process_dig(client: DFHackClient) -> None:
    """Tell the game to process dig designations on the next tick.

    Setting dig bits directly (Lua) does not set the game's
    ``process_dig`` flag — only the UI does that — so without this the
    game may not create FellTree/Dig jobs from a designation for a long
    time. Verified live 2026-11-25: a marked tree spawned no FellTree
    job in 65s of ticks, then the job appeared within 2s of calling
    ``dfhack.job.checkDesignationsNow()`` (which just sets that flag).
    The flag is only a hint; it is safe to set while paused.
    """
    client.run_lua("dfhack.job.checkDesignationsNow()")


# -- observation read-backs -------------------------------------------------

def _read_section(client: DFHackClient, section: str,
                  timeout: float = 30.0) -> dict[str, Any]:
    """Read one observe section; a failed section is a transport failure.

    The action cannot be verified without its read-back, so a section
    error means "outcome unknown", not "action failed".
    """
    state = observe.collect(client, sections=(section,), timeout=timeout)
    for err in state.get("errors") or []:
        if err.get("section") == section:
            raise _Fail("transport",
                        f"read-back section {section!r} failed: "
                        f"{err.get('error')}")
    return state[section]


def _map_size(client: DFHackClient) -> tuple[int, int, int]:
    """Map size in tiles (x, y) and z-level count, from the map section."""
    m = _read_section(client, "map")
    x_count, y_count = m["size_tiles"]
    return int(x_count), int(y_count), int(m["z_levels"])


def _check_box(client: DFHackClient, box: tuple[int, ...],
               timeout: float = 30.0) -> None:
    """Validate a (x0,y0,z0,x1,y1,z1) box against the map bounds."""
    if len(box) != 6 or not all(isinstance(v, int) for v in box):
        raise _Fail("precondition", f"bad box: {box!r} (want 6 ints)")
    x0, y0, z0, x1, y1, z1 = box
    if not (x0 <= x1 and y0 <= y1 and z0 <= z1):
        raise _Fail("precondition", f"box corners out of order: {box!r}")
    mx, my, mz = _map_size(client)
    if not (0 <= x0 and x1 < mx and 0 <= y0 and y1 < my
            and 0 <= z0 and z1 < mz):
        raise _Fail("precondition",
                    f"box {box!r} outside map 0..{mx - 1}, 0..{my - 1}, "
                    f"0..{mz - 1}")


def _wait_for(predicate: Callable[[], Any], timeout: float,
              interval: float = 0.5) -> Any:
    """Poll ``predicate`` until it returns a truthy value, or None.

    Bounded: never waits past ``timeout`` seconds. No retries of the
    underlying mutation — only re-reads.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


# -- actions ----------------------------------------------------------------

def designate_dig(client: DFHackClient, box: tuple[int, ...],
                  mode: str = "dig",
                  timeout: float = 30.0) -> ActionResult:
    """Designate a rectangle for digging (or clear it with mode 'clear').

    Verification: a targeted probe counts dig designations in the rect
    before and after. For a set, every tile must end up designated in the
    requested mode; for a clear, none may remain. The game is left paused
    throughout — no Dig job spawns, so no terrain changes (see ACTIONS.md
    for why the job-spawn check lives on chop/gather instead).
    """
    started = time.monotonic()
    mode_lua = DIG_MODES.get(mode)
    if mode_lua is None:
        raise _Fail("precondition",
                    f"unknown dig mode {mode!r} (choose from "
                    f"{', '.join(sorted(DIG_MODES))})")
    _check_box(client, box, timeout=timeout)
    params = {"x0": box[0], "y0": box[1], "z0": box[2],
              "x1": box[3], "y1": box[4], "z1": box[5], "mode": mode_lua}
    before = _run_helper(client, "probe_dig.lua", params, timeout=timeout)
    if not before.get("ok", False):
        raise _Fail("transport",
                    f"dig read-back failed: {before.get('error')}")
    area = (box[3] - box[0] + 1) * (box[4] - box[1] + 1)
    out = _helper_or_fail(client, "act_dig.lua", params, timeout=timeout)
    if mode != "clear":
        # The game only acts on the designation once its process_dig
        # flag is set (see _flag_process_dig); set it now so the Dig
        # jobs appear on later ticks. The game stays paused, so nothing
        # spawns during this action.
        _flag_process_dig(client)
    after = _run_helper(client, "probe_dig.lua", params, timeout=timeout)
    if not after.get("ok", False):
        raise _Fail("transport",
                    f"dig read-back failed: {after.get('error')}")
    took_ms = round((time.monotonic() - started) * 1000)
    if mode == "clear":
        good = after["dig_total"] == 0
        want = "0 designated tiles"
    else:
        by_type = {e["type"]: e["count"]
                   for e in after.get("dig_by_type") or []}
        good = (after["dig_total"] == area
                and by_type.get(mode_lua, 0) == area)
        want = f"{area} tiles designated {mode_lua}"
    if not good:
        return ActionResult(
            ok=False, action="designate_dig",
            before={"dig_total": before["dig_total"]},
            after={"dig_total": after["dig_total"],
                   "dig_by_type": after.get("dig_by_type")},
            reason=(f"dig designation not verified: wanted {want}, "
                    f"observed {after['dig_total']} designated tiles "
                    f"in the rect"),
            error_kind="verification", took_ms=took_ms,
            detail={"box": list(box), "mode": mode,
                    "set": out.get("set"), "cleared": out.get("cleared")})
    return ActionResult(
        ok=True, action="designate_dig",
        before={"dig_total": before["dig_total"]},
        after={"dig_total": after["dig_total"],
               "dig_by_type": after.get("dig_by_type")},
        reason=(f"{after['dig_total']} tiles designated {mode_lua}"
                if mode != "clear"
                else "designations cleared")
        + f" in rect {list(box)}",
        took_ms=took_ms,
        detail={"box": list(box), "mode": mode,
                "set": out.get("set"), "cleared": out.get("cleared")})


def _plants_action(client: DFHackClient, kind: str,
                   box: tuple[int, ...], mark: bool,
                   job_timeout: float = DEFAULT_JOB_TIMEOUT,
                   timeout: float = 30.0) -> ActionResult:
    """Shared body for designate_chop / designate_gather (mark/unmark)."""
    started = time.monotonic()
    job_type = _PLANT_JOBS[kind]
    _check_box(client, box, timeout=timeout)
    params = {"x0": box[0], "y0": box[1], "z0": box[2],
              "x1": box[3], "y1": box[4], "z1": box[5],
              "kind": kind, "mark": mark}
    before = _run_helper(client, "probe_plants.lua", params, timeout=timeout)
    if not before.get("ok", False):
        raise _Fail("transport",
                    f"plant read-back failed: {before.get('error')}")
    if before["total"] == 0:
        raise _Fail("precondition", f"no {kind}s in area {list(box)}")
    # Jobs already at these tiles before the marking (e.g. a stale
    # FellTree job left by an earlier unmark — the game never removes
    # those) must not count as spawn evidence later: only a job with a
    # NEW id proves this marking was seen. Captured before the mutation
    # (in the fake the job spawns synchronously with the marking, so a
    # probe taken after it would already include the new job).
    before_ids: set[int] = set()
    if mark:
        tiles_before = [p["des"] for p in before["plants"]]
        bj = _run_helper(client, "probe_jobs_at.lua",
                         {"tiles": tiles_before, "types": [job_type]},
                         timeout=timeout)
        before_ids = {j["id"] for j in bj.get("jobs") or []}
    out = _helper_or_fail(client, "act_plants.lua", params, timeout=timeout)
    after = _run_helper(client, "probe_plants.lua", params, timeout=timeout)
    if not after.get("ok", False):
        raise _Fail("transport",
                    f"plant read-back failed: {after.get('error')}")
    took_ms = round((time.monotonic() - started) * 1000)
    want_marked = after["total"] if mark else 0
    if after["marked"] != want_marked:
        return ActionResult(
            ok=False, action=f"designate_{'chop' if kind == 'tree' else 'gather'}",
            before={"total": before["total"], "marked": before["marked"]},
            after={"total": after["total"], "marked": after["marked"]},
            reason=(f"plant marking not verified: wanted {want_marked} of "
                    f"{after['total']} {kind}s marked, observed "
                    f"{after['marked']}"),
            error_kind="verification", took_ms=took_ms,
            detail={"box": list(box), "kind": kind, "mark": mark,
                    "changed": len(out.get("changed") or []),
                    "already": len(out.get("already") or [])})
    if not mark:
        # Unmark path: the action's own effect is clearing the
        # designation, which is verified above (marked == 0). The
        # FellTree/GatherPlants jobs are the game's cleanup, and the two
        # behave differently — verified live 2026-11-25/26:
        #
        # * GatherPlants jobs leave the list within seconds of ticks
        #   after the designation is cleared (whether by removeJob or
        #   by the game itself), so the wait below normally ends clean.
        # * FellTree jobs (and Dig jobs) NEVER leave the list: not via
        #   dfhack.job.removeJob (returns true, job stays listed through
        #   thousands of ticks), not via the game's own designation
        #   processing (process_dig set + ticks with the designation
        #   cleared), and not via the game's cleanup on its own. The
        #   designation being cleared means the game will not create a
        #   NEW job, but the stale job stays listed — and a dwarf can
        #   still take it if the tree is reachable. So the unmark
        #   succeeds on the verified designation, and any jobs that
        #   remain after the bounded wait are REPORTED in
        #   detail["remaining_jobs"] rather than failing the action:
        #   failing would make chop-unmark unusable while hiding
        #   nothing. Manual unlink+delete of a job struct is NOT used:
        #   it removed one Dig job cleanly, then crashed the game when
        #   applied to three FellTree jobs (probable double-free of a
        #   struct removeJob had already deleted). See docs/ACTIONS.md.
        tiles = [p["des"] for p in after["plants"]]
        jobs = _run_helper(client, "probe_jobs_at.lua",
                           {"tiles": tiles, "types": [job_type]},
                           timeout=timeout)
        waited = False
        remaining: list[dict[str, Any]] = list(jobs.get("jobs") or [])
        # Only wait for job types the game is known to remove.
        # GatherPlants jobs leave the list within seconds of ticks after
        # the designation is cleared (latency varies with the game's
        # designation sweep, so the full job_timeout bound applies).
        # FellTree jobs NEVER leave it (see the comment above), so
        # waiting would only burn the whole bound on every chop unmark:
        # they are reported immediately instead.
        if jobs.get("count") and job_type != "FellTree":
            waited = True

            def _jobs_gone() -> bool:
                cur = _run_helper(client, "probe_jobs_at.lua",
                                  {"tiles": tiles, "types": [job_type]},
                                  timeout=timeout)
                return not cur.get("count")

            with _unpaused_for_ticks(client):
                gone = _wait_for(_jobs_gone, job_timeout, interval=0.25)
            if gone:
                remaining = []
            else:
                cur = _run_helper(client, "probe_jobs_at.lua",
                                  {"tiles": tiles, "types": [job_type]},
                                  timeout=timeout)
                remaining = list(cur.get("jobs") or [])
        took_ms = round((time.monotonic() - started) * 1000)
        reason = (f"unmarked {after['total']} {kind}(s) in "
                  f"{list(box)}; no {job_type} jobs remain")
        if remaining:
            reason = (f"unmarked {after['total']} {kind}(s) in "
                      f"{list(box)}; designation verified clear but "
                      f"{len(remaining)} {job_type} job(s) remain at "
                      f"their tiles (game does not remove them — see "
                      f"docs/ACTIONS.md)")
        return ActionResult(
            ok=True, action="designate_chop" if kind == "tree"
            else "designate_gather",
            before={"total": before["total"], "marked": before["marked"]},
            after={"total": after["total"], "marked": after["marked"]},
            reason=reason,
            took_ms=took_ms,
            detail={"box": list(box), "kind": kind, "mark": mark,
                    "changed": len(out.get("changed") or []),
                    "waited_for_job_removal": waited,
                    "remaining_jobs": remaining})
    # Mark path, tier 2: the game must act on the designation — but only
    # when something was newly marked. When everything was already marked
    # there is no new work to wait for (a stale mark with no job would
    # otherwise time out a no-op).
    changed_n = len(out.get("changed") or [])
    if changed_n == 0:
        return ActionResult(
            ok=True, action="designate_chop" if kind == "tree"
            else "designate_gather",
            before={"total": before["total"], "marked": before["marked"]},
            after={"total": after["total"], "marked": after["marked"]},
            reason=(f"{after['marked']} {kind}(s) already marked in "
                    f"{list(box)}; nothing new to wait for"),
            took_ms=took_ms,
            detail={"box": list(box), "kind": kind, "mark": mark,
                    "changed": 0,
                    "already": len(out.get("already") or [])})
    # Unpause briefly and wait for a FellTree/GatherPlants job at one of
    # the designation tiles — or for a marked plant to disappear (gathered
    # / felled faster than the poll interval). Either proves the game saw it.
    # First flag the designation for processing: without process_dig the
    # game may not scan the new designation at all (see _flag_process_dig).
    _flag_process_dig(client)
    tiles = [p["des"] for p in after["plants"]]

    def _job_or_gone() -> Any:
        jobs = _run_helper(client, "probe_jobs_at.lua",
                           {"tiles": tiles, "types": [job_type]},
                           timeout=timeout)
        fresh = [j for j in jobs.get("jobs") or []
                 if j["id"] not in before_ids]
        if fresh:
            return {"jobs": fresh}
        now = _run_helper(client, "probe_plants.lua", params,
                          timeout=timeout)
        gone = [p for p in now.get("plants") or []
                if tuple(p["pos"]) in {tuple(q["pos"])
                                       for q in after["plants"]}
                and not p["marked"]]
        # A marked plant that is no longer marked and no longer exists in
        # the rect at all means it was harvested; detect via total drop.
        if now.get("total", after["total"]) < after["total"]:
            return {"harvested": True,
                    "total_now": now.get("total")}
        if gone:
            return {"unmarked_plants": gone}
        return None

    with _unpaused_for_ticks(client):
        seen = _wait_for(_job_or_gone, job_timeout, interval=0.25)
    took_ms = round((time.monotonic() - started) * 1000)
    if not seen:
        return ActionResult(
            ok=False, action="designate_chop" if kind == "tree"
            else "designate_gather",
            before={"total": before["total"], "marked": before["marked"]},
            after={"total": after["total"], "marked": after["marked"]},
            reason=(f"designation set ({after['marked']} {kind}s marked) "
                    f"but no {job_type} job appeared at their tiles "
                    f"within {job_timeout}s of unpausing"),
            error_kind="timeout", took_ms=took_ms,
            detail={"box": list(box), "kind": kind, "mark": mark,
                    "changed": len(out.get("changed") or [])})
    return ActionResult(
        ok=True, action="designate_chop" if kind == "tree"
        else "designate_gather",
        before={"total": before["total"], "marked": before["marked"]},
        after={"total": after["total"], "marked": after["marked"]},
        reason=(f"marked {after['marked']} {kind}(s) in {list(box)}; "
                f"game spawned {job_type} work {seen}"),
        took_ms=took_ms,
        detail={"box": list(box), "kind": kind, "mark": mark,
                "changed": len(out.get("changed") or []),
                "job_evidence": seen})


def designate_chop(client: DFHackClient, box: tuple[int, ...],
                   mark: bool = True,
                   job_timeout: float = DEFAULT_JOB_TIMEOUT,
                   timeout: float = 30.0) -> ActionResult:
    """Mark trees for chopping in a rect (mark=False undoes it)."""
    return _plants_action(client, "tree", box, mark,
                          job_timeout=job_timeout, timeout=timeout)


def designate_gather(client: DFHackClient, box: tuple[int, ...],
                     mark: bool = True,
                     job_timeout: float = DEFAULT_JOB_TIMEOUT,
                     timeout: float = 30.0) -> ActionResult:
    """Mark shrubs for gathering in a rect (mark=False undoes it)."""
    return _plants_action(client, "shrub", box, mark,
                          job_timeout=job_timeout, timeout=timeout)


def manager_order_create(client: DFHackClient, job_type: str,
                         amount: int = 1,
                         timeout: float = 30.0) -> ActionResult:
    """Create a manager order; verify it appears in the jobs section."""
    started = time.monotonic()
    if amount < 1:
        raise _Fail("precondition", f"amount must be >= 1, got {amount}")
    before = _read_section(client, "jobs", timeout=timeout)
    out = _helper_or_fail(client, "act_order.lua",
                          {"mode": "create", "job_type": job_type,
                           "amount": amount},
                          timeout=timeout)
    after = _read_section(client, "jobs", timeout=timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    order = next((o for o in after.get("manager_orders") or []
                  if o.get("id") == out["id"]), None)
    base = {"job_type": job_type, "amount": amount,
            "order_id": out["id"]}
    if order is None:
        return ActionResult(
            ok=False, action="manager_order_create",
            before={"manager_order_count":
                    before.get("manager_order_count")},
            after={"manager_order_count":
                   after.get("manager_order_count")},
            reason=(f"manager order #{out['id']} ({job_type} x{amount}) "
                    f"created but not found on re-read"),
            error_kind="verification", took_ms=took_ms, detail=base)
    return ActionResult(
        ok=True, action="manager_order_create",
        before={"manager_order_count": before.get("manager_order_count")},
        after={"manager_order_count": after.get("manager_order_count"),
               "order": order},
        reason=(f"manager order #{out['id']}: {job_type} x{amount} "
                f"(left {order.get('amount_left')}/"
                f"{order.get('amount_total')})"),
        took_ms=took_ms, detail=base)


def manager_order_remove(client: DFHackClient, order_id: int,
                         timeout: float = 30.0) -> ActionResult:
    """Remove a manager order by id; verify it is gone on re-read."""
    started = time.monotonic()
    before = _read_section(client, "jobs", timeout=timeout)
    if not any(o.get("id") == order_id
               for o in before.get("manager_orders") or []):
        raise _Fail("precondition",
                    f"no manager order with id {order_id}")
    out = _helper_or_fail(client, "act_order.lua",
                          {"mode": "remove", "order_id": order_id},
                          timeout=timeout)
    after = _read_section(client, "jobs", timeout=timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    if any(o.get("id") == order_id
           for o in after.get("manager_orders") or []):
        return ActionResult(
            ok=False, action="manager_order_remove",
            before={"manager_order_count":
                    before.get("manager_order_count")},
            after={"manager_order_count":
                   after.get("manager_order_count")},
            reason=(f"manager order #{order_id} still present after "
                    f"removal"),
            error_kind="verification", took_ms=took_ms,
            detail={"order_id": order_id})
    return ActionResult(
        ok=True, action="manager_order_remove",
        before={"manager_order_count": before.get("manager_order_count")},
        after={"manager_order_count": after.get("manager_order_count")},
        reason=f"manager order #{order_id} ({out.get('job_type')}) removed",
        took_ms=took_ms, detail={"order_id": order_id,
                                 "job_type": out.get("job_type")})


def build_workshop(client: DFHackClient, kind: str,
                   pos: tuple[int, int, int],
                   build_timeout: float = DEFAULT_BUILD_TIMEOUT,
                   timeout: float = 30.0) -> ActionResult:
    """Place a workshop and wait for its construction to complete.

    Preconditions: the kind is known, the site is free, and at least one
    accessible unit of the required material exists (an item inside a
    building — e.g. the embark wagon — does not count: jobs cannot use
    it). The building appears in the buildings list immediately with a
    ConstructBuilding job; the game is then unpaused (if it was paused)
    and the action waits, bounded, for that job to finish. Completion is
    judged by the job disappearing while the building remains — the
    construction_stage value is recorded as evidence, not assumed. If the
    building vanishes instead, the game cancelled the job; the reason is
    taken from the newest announcement when one matches.
    """
    started = time.monotonic()
    spec = WORKSHOP_CATALOG.get(kind)
    if spec is None:
        raise _Fail("precondition",
                    f"unknown workshop kind {kind!r} (choose from "
                    f"{', '.join(sorted(WORKSHOP_CATALOG))})")
    if len(pos) != 3 or not all(isinstance(v, int) for v in pos):
        raise _Fail("precondition", f"bad pos: {pos!r} (want 3 ints)")
    width, height = spec["width"], spec["height"]
    site = _run_helper(client, "probe_site.lua",
                       {"x": pos[0], "y": pos[1], "z": pos[2],
                        "width": width, "height": height},
                       timeout=timeout)
    if not site.get("ok", False):
        raise _Fail("transport",
                    f"site read-back failed: {site.get('error')}")
    if not site.get("free", False):
        raise _Fail("precondition",
                    "site not free: " + "; ".join(site.get("problems") or []))
    mat = _run_helper(client, "probe_material.lua",
                      {"item_type": spec["material"]}, timeout=timeout)
    if not mat.get("ok", False):
        raise _Fail("transport",
                    f"material read-back failed: {mat.get('error')}")
    if mat.get("accessible", 0) < 1:
        raise _Fail(
            "precondition",
            f"no accessible {spec['material']} for a {kind} workshop "
            f"({mat.get('total', 0)} in stock, all inside buildings — "
            f"deconstruct the wagon or chop a tree first)")
    before = _read_section(client, "buildings", timeout=timeout)
    out = _helper_or_fail(client, "act_build.lua",
                          {"type": spec["type"], "subtype": spec["subtype"],
                           "x": pos[0], "y": pos[1], "z": pos[2],
                           "width": width, "height": height},
                          timeout=timeout)
    building_id = out["id"]
    after_place = _read_section(client, "buildings", timeout=timeout)
    placed = next((b for b in after_place.get("list") or []
                   if b.get("id") == building_id), None)
    if placed is None:
        raise _Fail("verification",
                    f"workshop #{building_id} placed but not found in "
                    f"buildings on re-read")

    def _construction_done() -> Any:
        cur = _read_section(client, "buildings", timeout=timeout)
        b = next((x for x in cur.get("list") or []
                  if x.get("id") == building_id), None)
        if b is None:
            return {"cancelled": True}
        jobs = _read_section(client, "jobs", timeout=timeout)
        mine = [j for j in jobs.get("list") or []
                if j.get("type") == "ConstructBuilding"
                and j.get("pos") == b.get("center")]
        if not mine:
            return {"building": b}
        return None

    with _unpaused_for_ticks(client):
        done = _wait_for(_construction_done, build_timeout, interval=2.0)
    took_ms = round((time.monotonic() - started) * 1000)
    base = {"kind": kind, "pos": list(pos), "building_id": building_id,
            "stage_at_placement": out.get("construction_stage")}
    if done is None:
        return ActionResult(
            ok=False, action="build_workshop",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count"),
                   "building": placed},
            reason=(f"workshop #{building_id} placed but construction did "
                    f"not finish within {build_timeout}s"),
            error_kind="timeout", took_ms=took_ms, detail=base)
    if done.get("cancelled"):
        reason = (f"workshop #{building_id} placed but the game "
                  f"cancelled its construction")
        try:
            reps = _read_section(client, "reports", timeout=timeout)
            texts = [a.get("text", "")
                     for a in reps.get("announcements") or []]
            cancel = next((t for t in reversed(texts)
                           if "cancels" in t or "unable to complete" in t),
                          None)
            if cancel:
                reason += f": {cancel!r}"
        except _Fail:
            pass
        return ActionResult(
            ok=False, action="build_workshop",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count")},
            reason=reason, error_kind="verification", took_ms=took_ms,
            detail=base)
    final = done["building"]
    return ActionResult(
        ok=True, action="build_workshop",
        before={"building_count": before.get("count")},
        after={"building_count": after_place.get("count"),
               "building": final},
        reason=(f"{kind} workshop #{building_id} built at "
                f"{final.get('center')} "
                f"(construction_stage {final.get('construction_stage')})"),
        took_ms=took_ms, detail={**base,
                                 "stage_final":
                                     final.get("construction_stage")})


def labor_toggle(client: DFHackClient, unit: str | int, labor: str,
                 on: bool, timeout: float = 30.0) -> ActionResult:
    """Enable/disable a labor on one citizen, by name or unit id."""
    started = time.monotonic()
    if isinstance(unit, str) and not unit:
        raise _Fail("precondition", "empty unit name")
    params: dict[str, Any] = {"unit_id": 0, "name": "", "labor": labor,
                              "on": on}
    if isinstance(unit, int):
        params["unit_id"] = unit
    else:
        params["name"] = unit
    before = _read_section(client, "units", timeout=timeout)
    target_before = _find_citizen(before, unit)
    if target_before is None:
        raise _Fail("precondition", f"no citizen matching {unit!r}")
    out = _helper_or_fail(client, "act_labor.lua", params, timeout=timeout)
    after = _read_section(client, "units", timeout=timeout)
    target_after = _find_citizen(after, out["id"])
    took_ms = round((time.monotonic() - started) * 1000)
    base = {"unit": unit, "unit_id": out["id"], "name": out.get("name"),
            "labor": labor, "on": on}
    if target_after is None:
        raise _Fail("verification",
                    f"citizen #{out['id']} vanished on re-read")
    has_labor = labor in (target_after.get("labors") or [])
    if has_labor != on:
        return ActionResult(
            ok=False, action="labor_toggle",
            before={"labors": target_before.get("labors")},
            after={"labors": target_after.get("labors")},
            reason=(f"labor {labor} on {out.get('name')} not verified: "
                    f"wanted {'on' if on else 'off'}, observed "
                    f"{'on' if has_labor else 'off'}"),
            error_kind="verification", took_ms=took_ms, detail=base)
    return ActionResult(
        ok=True, action="labor_toggle",
        before={"labors": target_before.get("labors")},
        after={"labors": target_after.get("labors")},
        reason=(f"labor {labor} {'enabled' if on else 'disabled'} on "
                f"{out.get('name')}"),
        took_ms=took_ms, detail=base)


def _find_citizen(units_section: dict[str, Any],
                  unit: str | int) -> Optional[dict[str, Any]]:
    """Find a citizen in a units section by id or by exact name."""
    for c in units_section.get("citizens") or []:
        if isinstance(unit, int) and c.get("id") == unit:
            return c
        if isinstance(unit, str) and c.get("name") == unit:
            return c
    return None


# -- entry point ------------------------------------------------------------

ACTIONS: dict[str, Callable[..., ActionResult]] = {
    "designate_dig": designate_dig,
    "designate_chop": designate_chop,
    "designate_gather": designate_gather,
    "manager_order_create": manager_order_create,
    "manager_order_remove": manager_order_remove,
    "build_workshop": build_workshop,
    "labor_toggle": labor_toggle,
}


def act(client: DFHackClient, name: str, **kwargs: Any) -> ActionResult:
    """Run one verified action by name; the daemon's entry point.

    Returns an :class:`ActionResult` — never raises for a failed action.
    Unknown action names raise ValueError (a caller bug, not a game
    state). Transport failures are reported as ``error_kind="transport"``
    with ``ok=False``; the outcome is unknown and the caller must re-read
    state before retrying.
    """
    fn = ACTIONS.get(name)
    if fn is None:
        raise ValueError(
            f"unknown action {name!r} (choose from "
            f"{', '.join(sorted(ACTIONS))})")
    started = time.monotonic()
    try:
        result = fn(client, **kwargs)
    except _Fail as exc:
        result = ActionResult(
            ok=False, action=name, reason=exc.reason,
            error_kind=exc.kind,
            took_ms=round((time.monotonic() - started) * 1000))
    except (DFHackError, ValueError, OSError) as exc:
        # Transport failure or a bad read-back: outcome unknown.
        result = ActionResult(
            ok=False, action=name,
            reason=f"transport failure: {exc}",
            error_kind="transport",
            took_ms=round((time.monotonic() - started) * 1000))
    return result
