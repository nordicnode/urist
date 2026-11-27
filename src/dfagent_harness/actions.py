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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dfhack_rpc import DFHackClient, DFHackError
from dfhack_rpc.proto import CoreProtocol_pb2 as core
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr

from . import observe

__all__ = [
    "ActionResult",
    "ACTIONS",
    "DIG_MODES",
    "WORKSHOP_CATALOG",
    "JOB_SPECS",
    "FURNITURE_ITEMS",
    "NOBLE_POSITIONS",
    "NOBLES_SCREEN_ORDER",
    "act",
    "designate_dig",
    "designate_chop",
    "designate_gather",
    "manager_order_create",
    "manager_order_remove",
    "build_workshop",
    "labor_toggle",
    "queue_job",
    "build_farm_plot",
    "build_furniture",
    "deconstruct_building",
    "nobles",
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

#: CLI dig mode -> df.job_type name of the job the game creates for
#: it (verified live 2026-11-26: a down-stair designation creates a
#: CarveDownwardStaircase job, NOT a Dig job — dig_to_completion used
#: to wait only for Dig/DigChannel, so it timed out on stairs/ramps
#: even though the dwarf dug the tile). The job types are the real
#: runtime enums (tests/fixtures/runtime-enums-0.47.05-r8.json).
DIG_JOB_TYPES: dict[str, str] = {
    "dig": "Dig",
    "channel": "DigChannel",
    "ramp": "CarveRamp",
    "up-stair": "CarveUpwardStaircase",
    "down-stair": "CarveDownwardStaircase",
    "up-down-stair": "CarveUpDownStaircase",
}

#: Workshop kind -> building definition. ``material`` is the df.item_type
#: whose accessible stock the precondition checks (see probe_material).
#: NOTE (phase 4, verified live 2026-11-26): the still accepts WOOD —
#: still #10 was built from a log with no stone in stock. The catalog
#: keeps the stone option too; the check passes when ANY listed
#: material is accessible.
WORKSHOP_CATALOG: dict[str, dict[str, Any]] = {
    "carpenter": {"type": "Workshop", "subtype": "Carpenters",
                  "width": 3, "height": 3, "material": "WOOD",
                  "materials": ["WOOD"]},
    "mason": {"type": "Workshop", "subtype": "Masons",
              "width": 3, "height": 3, "material": "BOULDER",
              "materials": ["BOULDER"]},
    "still": {"type": "Workshop", "subtype": "Still",
              "width": 3, "height": 3, "material": "BOULDER",
              "materials": ["BOULDER", "WOOD"]},
    "kitchen": {"type": "Workshop", "subtype": "Kitchen",
                "width": 3, "height": 3, "material": "BOULDER",
                "materials": ["BOULDER"]},
}

#: Queueable workshop jobs (phase 4). Workshop item jobs are REACTIONS
#: in 0.47.05 (see the reaction catalog probed live 2026-11-26:
#: df.reaction.find(44) == BREW_DRINK_FROM_PLANT; MAKE WOODEN BED == 2).
#: ``job_type`` 211 is CustomReaction; ``reaction_name`` selects the
#: reaction. Plain jobs (PrepareMeal, MakeBarrel) need no reaction.
#: ``skill`` is the labor-relevant skill (informational).
JOB_SPECS: dict[str, dict[str, Any]] = {
    # Still (needs a brewable plant + an empty barrel per job).
    "brew": {"job_type": 211, "reaction_name": "BREW_DRINK_FROM_PLANT",
             "skill": "BREWING"},
    "brew_fruit": {"job_type": 211,
                   "reaction_name": "BREW_DRINK_FROM_PLANT_GROWTH",
                   "skill": "BREWING"},
    # Kitchen.
    "cook": {"job_type": 115, "reaction_name": None, "skill": "COOK"},
    # Carpenter (one log per job).
    "make_bed": {"job_type": 211, "reaction_name": "MAKE WOODEN BED",
                 "skill": "CARPENTRY"},
    "make_table": {"job_type": 211, "reaction_name": "MAKE WOODEN TABLE",
                   "skill": "CARPENTRY"},
    "make_chair": {"job_type": 211, "reaction_name": "MAKE WOODEN CHAIR",
                   "skill": "CARPENTRY"},
    "make_door": {"job_type": 211, "reaction_name": "MAKE WOODEN DOOR",
                  "skill": "CARPENTRY"},
    "make_barrel": {"job_type": 211, "reaction_name": "MAKE WOODEN BARREL",
                    "skill": "CARPENTRY"},
    "make_bucket": {"job_type": 211, "reaction_name": "MAKE WOODEN BUCKET",
                    "skill": "CARPENTRY"},
    "make_bin": {"job_type": 211, "reaction_name": "MAKE WOODEN BIN",
                 "skill": "CARPENTRY"},
    "make_chest": {"job_type": 211, "reaction_name": "MAKE WOODEN CHEST",
                   "skill": "CARPENTRY"},
    "make_cabinet": {"job_type": 211,
                     "reaction_name": "MAKE WOODEN CABINET",
                     "skill": "CARPENTRY"},
}

#: Furniture kind -> item type that must exist in stock to place it
#: (the Construct<kind> job consumes the item).
FURNITURE_ITEMS: dict[str, str] = {
    "Bed": "BED", "Table": "TABLE", "Chair": "CHAIR", "Door": "DOOR",
    "Coffin": "COFFIN", "Chest": "CHEST", "Cabinet": "CABINET",
    "ArmorStand": "ARMORSTAND", "WeaponRack": "WEAPONRACK",
    "Statue": "STATUE", "Floodgate": "FLOODGATE", "Hatch": "HATCH",
    "Grate": "GRATE",
}

#: Noble responsibility -> raw position id (probed live 2026-11-26
#: from entity_raw.positions; used only for display — appointment
#: itself is UI-only, see ui.py).
NOBLE_POSITIONS: dict[str, int] = {
    "manager": 10, "broker": 12, "bookkeeper": 13,
}

#: Order of positions on the nobles screen (n key), top to bottom —
#: verified live 2026-11-26 (screenshot). Used by ui.appoint_noble.
NOBLES_SCREEN_ORDER: list[str] = [
    "expedition_leader", "militia_commander", "sheriff", "hammerer",
    "manager", "chief_medical_dwarf", "broker", "bookkeeper",
]

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
    # Failure diagnosis (GOAL.md step 5, layer 4): the fix for a
    # failed action, in plain words (the corrective catalog action
    # + what it needs). None when the action succeeded or the cause
    # is not recognised.
    fix: Optional[str] = None

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
            "fix": self.fix,
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
    flag does not stick. Known flake (ACTIONS.md): after a world
    reload, SetPauseState(False) sometimes fails to stick twice in a
    row; a Space keypress restores it. So on a failed set we send one
    Space keypress via PassKeyboardEvent and retry once — that is the
    observed recovery, not a blind retry loop.
    """
    try:
        client.call("SetPauseState", rfr.SingleBool(Value=paused),
                    core.EmptyMessage)
        actual = get_paused(client)
        if actual == paused:
            return actual
    except Exception:
        pass
    _send_space_key(client)
    client.call("SetPauseState", rfr.SingleBool(Value=paused),
                core.EmptyMessage)
    actual = get_paused(client)
    if actual != paused:
        raise _Fail("verification",
                    f"pause flag did not stick: wanted {paused}, got {actual}")
    return actual


def _send_space_key(client: DFHackClient) -> None:
    """Send one Space keypress (down + up) via RFR PassKeyboardEvent.

    Space is the game's pause toggle; used only as the recovery for
    a SetPauseState that did not stick after a reload.
    """
    for ev_type, state in ((2, 1), (3, 0)):
        client.call("PassKeyboardEvent",
                    rfr.KeyboardEvent(type=ev_type, sym=32, state=state,
                                      unicode=32, scancode=0, mod=0),
                    core.EmptyMessage)
        time.sleep(0.05)


def _wait_for_paused(client: DFHackClient, predicate: Callable[[], Any],
                     timeout: float, burst: float = 1.0) -> Any:
    """Poll ``predicate`` until it returns a truthy value, or None.

    Pause-before-read (the read-safety rule, world-model design §8):
    game state is NEVER read while the game is running. The loop runs
    in bursts: unpause briefly so the game ticks, re-pause (verified),
    then read the predicate while paused. Repeat until the predicate
    holds or the timeout (wall clock) expires. The entry pause state
    is restored on exit, even on failure; a restore failure is raised
    as a verification failure (the game is left in a known-reported
    state, never silently running).

    ``burst`` is the unpaused window per iteration in wall seconds
    (~46 game ticks at the measured ~46 ticks/s). One second is enough
    for a job to spawn after a designation is processed, and short
    enough that a read never happens far from a pause. The old pattern
    (unpause for the whole wait, polling probes every 0.25s while the
    game ticked) is what killed DF three times in the live suite on
    2026-11-25 — RPC reads of the jobs list while the game ticks can
    catch a freed struct (one run ended "free(): double free detected
    in tcache 2"). No retries of the underlying mutation — only
    re-reads.
    """
    was_paused = get_paused(client)
    deadline = time.monotonic() + timeout
    try:
        while True:
            # Read while paused (pause first if the game was running).
            if not get_paused(client):
                set_paused(client, True)
            value = predicate()
            if value:
                return value
            if time.monotonic() >= deadline:
                return None
            # Burst: let the game tick, then loop back to the paused read.
            set_paused(client, False)
            time.sleep(min(burst, max(0.0, deadline - time.monotonic())))
            set_paused(client, True)
    finally:
        if get_paused(client) != was_paused:
            set_paused(client, was_paused)


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


def dig_to_completion(client: DFHackClient, box: tuple[int, ...],
                      mode: str = "dig",
                      job_timeout: float = DEFAULT_JOB_TIMEOUT,
                      complete_timeout: float = 180.0,
                      timeout: float = 30.0) -> ActionResult:
    """The end-to-end dig loop (the digging gap): check the site,
    designate, wait for a Dig job to spawn, wait for the dig to
    complete (designation gone AND terrain changed).

    The site check (digging.check_dig_box) runs first and refuses
    unreachable / hazardous sites before anything is designated — a
    down-stair on buried soil sets the bits but the game never turns
    it into a job, and a down-stair over magma floods the fort. The
    job wait uses the burst pattern (_wait_for_paused: short
    unpaused bursts, reads only while paused) and only a NEW job id
    counts as spawn evidence (a stale Dig job from an earlier dig
    must not). Completion is verified by digging.verify_dig, not by
    the job disappearing (Dig jobs can linger in the list after the
    terrain changes).
    """
    from . import digging
    started = time.monotonic()
    # 1. Site check (paused read): reachable + no hazard.
    check = digging.check_dig_box(client, box, mode)
    if not check["ok"]:
        raise _Fail("precondition",
                    f"dig site refused: {check['reason']}")
    # 2. Capture the Dig jobs already at these tiles (a stale job
    # from an earlier dig must not count as spawn evidence).
    tiles = [[x, y, z] for x in range(box[0], box[3] + 1)
             for y in range(box[1], box[4] + 1)
             for z in range(box[2], box[5] + 1)]
    # The job type depends on the mode (a down-stair is a
    # CarveDownwardStaircase job, not a Dig job — see DIG_JOB_TYPES).
    job_types = [DIG_JOB_TYPES[mode]]
    before = _run_helper(client, "probe_jobs_at.lua",
                         {"tiles": tiles, "types": job_types},
                         timeout=timeout)
    before_ids = {j["id"] for j in before.get("jobs") or []}
    # 3. Designate.
    des = designate_dig(client, box, mode=mode, timeout=timeout)
    if not des.ok:
        return des
    # 4. Wait for a NEW Dig job at one of the tiles.
    def _job() -> Any:
        cur = _run_helper(client, "probe_jobs_at.lua",
                          {"tiles": tiles, "types": job_types},
                          timeout=timeout)
        fresh = [j for j in cur.get("jobs") or []
                 if j["id"] not in before_ids]
        return fresh[0] if fresh else None

    job = _wait_for_paused(client, _job, job_timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    if not job:
        return ActionResult(
            ok=False, action="dig_to_completion",
            before={"dig_total": des.before.get("dig_total")},
            after={"dig_total": des.after.get("dig_total")},
            reason=(f"designation set ({des.after.get('dig_total')} "
                    f"tiles) but no Dig job appeared at their tiles "
                    f"within {job_timeout}s of unpausing — the site "
                    f"may be unreachable (see digging.check_dig_site)"),
            error_kind="timeout", took_ms=took_ms,
            detail={"box": list(box), "mode": mode,
                    "site_check": check["reason"]})
    # 5. Wait for completion (designation gone + terrain changed).
    def _done() -> Any:
        v = digging.verify_dig(client, box, mode)
        return v if v["complete"] else None

    done = _wait_for_paused(client, _done, complete_timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    if not done:
        cur = digging.verify_dig(client, box, mode)
        return ActionResult(
            ok=False, action="dig_to_completion",
            before={"dig_total": des.before.get("dig_total")},
            after={"dig_total": des.after.get("dig_total")},
            reason=(f"Dig job {job.get('id')} spawned but the dig "
                    f"did not complete within {complete_timeout}s: "
                    f"{cur['reason']}"),
            error_kind="timeout", took_ms=took_ms,
            detail={"box": list(box), "mode": mode,
                    "job": job, "verify": cur})
    return ActionResult(
        ok=True, action="dig_to_completion",
        before={"dig_total": des.before.get("dig_total")},
        after={"dig_total": des.after.get("dig_total")},
        reason=(f"dug {mode} in {list(box)}: Dig job "
                f"{job.get('id')} spawned, {done['reason']}"),
        took_ms=took_ms,
        detail={"box": list(box), "mode": mode, "job": job,
                "verify": done})


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

            gone = _wait_for_paused(client, _jobs_gone, job_timeout)
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
    # Wait (burst pattern: short unpaused bursts, reads only while
    # paused) for a FellTree/GatherPlants job at one of the designation
    # tiles — or for a marked plant to disappear (gathered / felled
    # faster than the poll interval). Either proves the game saw it.
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

    seen = _wait_for_paused(client, _job_or_gone, job_timeout)
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


def _site_fix_hint(problems: list[str]) -> str:
    """Actionable fix for a 'site not free' failure.

    M1 run #5: the model tried the same shrub-blocked still site
    twice and never cleared it or moved, because the error named
    the blocker but not what to DO about it. The hint names the
    fix — including the blocked tile, so the model can gather it
    or move — instead of retrying the same site.
    """
    import re
    text = " ".join(problems or [])
    lower = text.lower()
    tiles = re.findall(r"tile (\d+,\d+)", text)
    tile = f" ({tiles[0]})" if tiles else ""
    if "shrub" in lower or "plant" in lower:
        return ("Fix: gather the blocking plant(s) first "
                f"(designate_gather on a small box covering{tile}), "
                "wait for the gather to finish (advance the clock), "
                "then retry the build — or pick a different free "
                "3x3 site.")
    if "unit" in lower:
        return ("Fix: wait for the unit to move, or pick a "
                "different free 3x3 site.")
    return "Fix: pick a different free 3x3 site on open ground."


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
    # Normalize the kind: the model reads "Still" from the catalog's
    # subtype and passes it capitalised; the registry keys are
    # lowercase. Accept any case (M1, 2026-11-26: the model failed
    # the still build twice on 'Still' vs 'still').
    kind = str(kind).strip().lower()
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
        problems = site.get("problems") or []
        raise _Fail("precondition",
                    "site not free: " + "; ".join(problems) + ". "
                    + _site_fix_hint(problems))
    mat = None
    for mat_type in spec.get("materials") or [spec["material"]]:
        probe = _run_helper(client, "probe_material.lua",
                            {"item_type": mat_type}, timeout=timeout)
        if not probe.get("ok", False):
            raise _Fail("transport",
                        f"material read-back failed: {probe.get('error')}")
        if probe.get("accessible", 0) >= 1:
            mat = probe
            break
    if mat is None:
        raise _Fail(
            "precondition",
            f"no accessible material for a {kind} workshop (tried "
            f"{', '.join(spec.get('materials') or [spec['material']])} — "
            f"deconstruct the wagon or chop a tree first)")
    before = _read_section(client, "buildings", timeout=timeout)
    out = _helper_or_fail(client, "act_build.lua",
                          {"type": spec["type"], "subtype": spec["subtype"],
                           "x": pos[0], "y": pos[1], "z": pos[2],
                           "width": width, "height": height,
                           "mat_type": mat.get("mat_type"),
                           "mat_index": mat.get("mat_index")},
                          timeout=timeout)
    building_id = out["id"]
    after_place = _read_section(client, "buildings", timeout=timeout)
    placed = next((b for b in after_place.get("list") or []
                   if b.get("id") == building_id), None)
    if placed is None:
        raise _Fail("verification",
                    f"workshop #{building_id} placed but not found in "
                    f"buildings on re-read")
    # Fail fast on a mat-NONE building: without an assigned material
    # the ConstructBuilding job can never be worked (carpenter #22,
    # 2026-11-26) and the wait below would burn the whole timeout.
    # The building's material is read back through the material probe
    # helper (buildings.lua does not expose mat_type).
    placed_mat = _run_helper(client, "probe_bldg_mat.lua",
                             {"building_id": building_id}, timeout=timeout)
    if placed_mat.get("mat_type", -1) in (None, -1):
        return ActionResult(
            ok=False, action="build_workshop",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count"),
                   "building": placed},
            reason=(f"workshop #{building_id} placed with no material "
                    f"(mat NONE) — the game assigned no construction "
                    f"item; deconstruct it and retry"),
            error_kind="verification",
            took_ms=round((time.monotonic() - started) * 1000),
            detail={"kind": kind, "pos": list(pos),
                    "building_id": building_id})

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

    done = _wait_for_paused(client, _construction_done, build_timeout)
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


def _wait_construction(client: DFHackClient, building_id: int,
                       build_timeout: float,
                       timeout: float = 30.0) -> dict[str, Any] | None:
    """Wait for a building's ConstructBuilding job to clear.

    Burst pattern: the game ticks in short unpaused bursts and every
    read happens while paused (see _wait_for_paused).

    Returns ``{"building": <buildings entry>}`` when the building stands
    with no construction job left, ``{"cancelled": True}`` when the
    building vanished (game cancelled it), or None on timeout.
    """
    def _done() -> Any:
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

    return _wait_for_paused(client, _done, build_timeout)


def _cancel_reason(client: DFHackClient, timeout: float = 30.0) -> str:
    """Newest matching cancellation announcement, if any."""
    try:
        reps = _read_section(client, "reports", timeout=timeout)
        texts = [a.get("text", "")
                 for a in reps.get("announcements") or []]
        cancel = next((t for t in reversed(texts)
                       if "cancels" in t or "unable to complete" in t),
                      None)
        return f": {cancel!r}" if cancel else ""
    except _Fail:
        return ""


def queue_job(client: DFHackClient, building_id: int, job: str,
              count: int = 1, timeout: float = 30.0) -> ActionResult:
    """Queue ``count`` copies of a workshop job on a building.

    ``job`` is a :data:`JOB_SPECS` name (``brew``, ``cook``,
    ``make_bed``, ...). Verification: the returned job ids appear in
    the world jobs list. The job being *worked* is not part of this
    action — the planner watches job_completed events for that.
    """
    started = time.monotonic()
    spec = JOB_SPECS.get(job)
    if spec is None:
        raise _Fail("precondition",
                    f"unknown job {job!r} (choose from "
                    f"{', '.join(sorted(JOB_SPECS))})")
    if count < 1:
        raise _Fail("precondition", f"count must be >= 1, got {count}")
    before = _read_section(client, "buildings", timeout=timeout)
    target = next((b for b in before.get("list") or []
                   if b.get("id") == building_id), None)
    if target is None:
        raise _Fail("precondition", f"no building #{building_id}")
    out = _helper_or_fail(client, "act_job.lua",
                          {"building_id": building_id,
                           "job_type": spec["job_type"],
                           "reaction_name": spec["reaction_name"],
                           "count": count},
                          timeout=timeout)
    after = _read_section(client, "jobs", timeout=timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    listed = {j.get("id") for j in after.get("list") or []}
    missing = [jid for jid in out.get("job_ids") or []
               if jid not in listed]
    base = {"building_id": building_id, "job": job, "count": count,
            "job_ids": out.get("job_ids"),
            "reaction_name": spec["reaction_name"]}
    if missing:
        return ActionResult(
            ok=False, action="queue_job",
            before={"job_count": before.get("count")},
            after={"job_count": after.get("count")},
            reason=(f"queued {job} x{count} on building #{building_id} "
                    f"but job ids {missing} not found in the world job "
                    f"list on re-read"),
            error_kind="verification", took_ms=took_ms, detail=base)
    return ActionResult(
        ok=True, action="queue_job",
        before={"job_count": before.get("count")},
        after={"job_count": after.get("count")},
        reason=(f"queued {job} x{count} on building #{building_id} "
                f"(jobs {out.get('job_ids')})"),
        took_ms=took_ms, detail=base)


def build_farm_plot(client: DFHackClient, x: int, y: int, z: int,
                    width: int = 3, height: int = 3,
                    build_timeout: float = DEFAULT_BUILD_TIMEOUT,
                    timeout: float = 30.0) -> ActionResult:
    """Place a farm plot and wait for its construction to finish.

    Verification: the plot appears in the buildings list, then its
    ConstructBuilding job clears while it remains. A plot on unsuitable
    ground (no soil) is cancelled by the game — reported as a
    verification failure with the cancellation text.
    """
    started = time.monotonic()
    if width < 1 or height < 1:
        raise _Fail("precondition",
                    f"bad farm size {width}x{height} (want >= 1)")
    site = _run_helper(client, "probe_site.lua",
                       {"x": x, "y": y, "z": z,
                        "width": width, "height": height},
                       timeout=timeout)
    if not site.get("ok", False):
        raise _Fail("transport",
                    f"site read-back failed: {site.get('error')}")
    if not site.get("free", False):
        problems = site.get("problems") or []
        raise _Fail("precondition",
                    "site not free: " + "; ".join(problems) + ". "
                    + _site_fix_hint(problems))
    before = _read_section(client, "buildings", timeout=timeout)
    out = _helper_or_fail(client, "act_farm.lua",
                          {"x": x, "y": y, "z": z,
                           "width": width, "height": height},
                          timeout=timeout)
    building_id = out["id"]
    after_place = _read_section(client, "buildings", timeout=timeout)
    placed = next((b for b in after_place.get("list") or []
                   if b.get("id") == building_id), None)
    if placed is None:
        raise _Fail("verification",
                    f"farm plot #{building_id} placed but not found in "
                    f"buildings on re-read")
    done = _wait_construction(client, building_id, build_timeout,
                              timeout=timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    base = {"pos": [x, y, z], "size": [width, height],
            "building_id": building_id}
    if done is None:
        return ActionResult(
            ok=False, action="build_farm_plot",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count"),
                   "building": placed},
            reason=(f"farm plot #{building_id} placed but construction "
                    f"did not finish within {build_timeout}s"),
            error_kind="timeout", took_ms=took_ms, detail=base)
    if done.get("cancelled"):
        return ActionResult(
            ok=False, action="build_farm_plot",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count")},
            reason=(f"farm plot #{building_id} placed but the game "
                    f"cancelled its construction"
                    f"{_cancel_reason(client, timeout=timeout)}"),
            error_kind="verification", took_ms=took_ms, detail=base)
    return ActionResult(
        ok=True, action="build_farm_plot",
        before={"building_count": before.get("count")},
        after={"building_count": after_place.get("count"),
               "building": done["building"]},
        reason=(f"farm plot #{building_id} built at "
                f"{done['building'].get('center')} ({width}x{height})"),
        took_ms=took_ms, detail=base)


def build_furniture(client: DFHackClient, kind: str,
                    pos: tuple[int, int, int],
                    build_timeout: float = DEFAULT_BUILD_TIMEOUT,
                    timeout: float = 30.0) -> ActionResult:
    """Place one furniture building (bed, table, chair, ...) and wait
    for its construction to finish.

    Precondition: a matching item exists in stock (the Construct job
    consumes it — e.g. a bed item from the carpenter). Verification:
    the building appears in the buildings list, then its construction
    job clears while it remains.
    """
    started = time.monotonic()
    item_type = FURNITURE_ITEMS.get(kind)
    if item_type is None:
        raise _Fail("precondition",
                    f"unknown furniture kind {kind!r} (choose from "
                    f"{', '.join(sorted(FURNITURE_ITEMS))})")
    if len(pos) != 3 or not all(isinstance(v, int) for v in pos):
        raise _Fail("precondition", f"bad pos: {pos!r} (want 3 ints)")
    site = _run_helper(client, "probe_site.lua",
                       {"x": pos[0], "y": pos[1], "z": pos[2],
                        "width": 1, "height": 1},
                       timeout=timeout)
    if not site.get("ok", False):
        raise _Fail("transport",
                    f"site read-back failed: {site.get('error')}")
    if not site.get("free", False):
        problems = site.get("problems") or []
        raise _Fail("precondition",
                    "site not free: " + "; ".join(problems) + ". "
                    + _site_fix_hint(problems))
    items = _read_section(client, "items", timeout=timeout)
    have = next((e.get("units", 0)
                 for e in items.get("by_type") or []
                 if e.get("type") == item_type), 0)
    if have < 1:
        raise _Fail("precondition",
                    f"no {item_type} item in stock to place a {kind} "
                    f"(make one at the carpenter first)")
    before = _read_section(client, "buildings", timeout=timeout)
    out = _helper_or_fail(client, "act_furniture.lua",
                          {"kind": kind, "x": pos[0], "y": pos[1],
                           "z": pos[2]},
                          timeout=timeout)
    building_id = out["id"]
    after_place = _read_section(client, "buildings", timeout=timeout)
    placed = next((b for b in after_place.get("list") or []
                   if b.get("id") == building_id), None)
    if placed is None:
        raise _Fail("verification",
                    f"{kind} #{building_id} placed but not found in "
                    f"buildings on re-read")
    done = _wait_construction(client, building_id, build_timeout,
                              timeout=timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    base = {"kind": kind, "pos": list(pos), "building_id": building_id}
    if done is None:
        return ActionResult(
            ok=False, action="build_furniture",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count"),
                   "building": placed},
            reason=(f"{kind} #{building_id} placed but construction did "
                    f"not finish within {build_timeout}s"),
            error_kind="timeout", took_ms=took_ms, detail=base)
    if done.get("cancelled"):
        return ActionResult(
            ok=False, action="build_furniture",
            before={"building_count": before.get("count")},
            after={"building_count": after_place.get("count")},
            reason=(f"{kind} #{building_id} placed but the game "
                    f"cancelled its construction"
                    f"{_cancel_reason(client, timeout=timeout)}"),
            error_kind="verification", took_ms=took_ms, detail=base)
    return ActionResult(
        ok=True, action="build_furniture",
        before={"building_count": before.get("count")},
        after={"building_count": after_place.get("count"),
               "building": done["building"]},
        reason=(f"{kind} #{building_id} built at "
                f"{done['building'].get('center')}"),
        took_ms=took_ms, detail=base)


def deconstruct_building(client: DFHackClient, building_id: int,
                         timeout: float = 30.0,
                         wait_timeout: float = 60.0) -> ActionResult:
    """Mark a building for deconstruction and wait until it is gone.

    Verification: the building disappears from the buildings list.
    The footprint's stale occupancy flag is cleared by the helper, so
    the site is reusable immediately (phase-2 finding).
    """
    started = time.monotonic()
    before = _read_section(client, "buildings", timeout=timeout)
    target = next((b for b in before.get("list") or []
                   if b.get("id") == building_id), None)
    if target is None:
        raise _Fail("precondition", f"no building #{building_id}")
    _helper_or_fail(client, "act_deconstruct.lua",
                    {"building_id": building_id}, timeout=timeout)

    def _gone() -> bool:
        cur = _read_section(client, "buildings", timeout=timeout)
        return not any(b.get("id") == building_id
                       for b in cur.get("list") or [])

    gone = _wait_for_paused(client, _gone, wait_timeout)
    took_ms = round((time.monotonic() - started) * 1000)
    after = _read_section(client, "buildings", timeout=timeout)
    if not gone:
        return ActionResult(
            ok=False, action="deconstruct_building",
            before={"building_count": before.get("count")},
            after={"building_count": after.get("count")},
            reason=(f"building #{building_id} marked for deconstruction "
                    f"but still present after {wait_timeout}s"),
            error_kind="timeout", took_ms=took_ms,
            detail={"building_id": building_id,
                    "type": target.get("type")})
    return ActionResult(
        ok=True, action="deconstruct_building",
        before={"building_count": before.get("count")},
        after={"building_count": after.get("count")},
        reason=(f"building #{building_id} ({target.get('type')}) "
                f"deconstructed"),
        took_ms=took_ms,
        detail={"building_id": building_id, "type": target.get("type")})


def nobles(client: DFHackClient,
           timeout: float = 30.0) -> dict[str, Any]:
    """Read noble appointments (read-only probe). Returns the raw
    probe result: ``{"ok": true, "nobles": {responsibility: [...]}}``.
    """
    return _run_helper(client, "probe_nobles.lua", {}, timeout=timeout)


# -- entry point ------------------------------------------------------------

ACTIONS: dict[str, Callable[..., ActionResult]] = {
    "designate_dig": designate_dig,
    "dig_to_completion": dig_to_completion,
    "designate_chop": designate_chop,
    "designate_gather": designate_gather,
    "manager_order_create": manager_order_create,
    "manager_order_remove": manager_order_remove,
    "build_workshop": build_workshop,
    "labor_toggle": labor_toggle,
    "queue_job": queue_job,
    "build_farm_plot": build_farm_plot,
    "build_furniture": build_furniture,
    "deconstruct_building": deconstruct_building,
}


def act(client: DFHackClient, name: str, **kwargs: Any) -> ActionResult:
    """Run one verified action by name; the daemon's entry point.

    Returns an :class:`ActionResult` — never raises for a failed action.
    Unknown action names raise ValueError (a caller bug, not a game
    state). Transport failures are reported as ``error_kind="transport"``
    with ``ok=False``; the outcome is unknown and the caller must re-read
    state before retrying.

    ``state`` (an observe state, popped from kwargs and NOT forwarded
    to the action) lets a failed action carry its fix (GOAL.md step 5,
    layer 4): the corrective catalog action + what it needs, with the
    current numbers. Without it the result has no fix.
    """
    fn = ACTIONS.get(name)
    if fn is None:
        raise ValueError(
            f"unknown action {name!r} (choose from "
            f"{', '.join(sorted(ACTIONS))})")
    # The observe state, for failure diagnosis only — never forwarded
    # to the action function (it takes only its own parameters).
    state = kwargs.pop("state", None)
    started = time.monotonic()
    # Read safety (world-model design §8): the whole action runs
    # under the pause-before-read gate. The action's read-backs
    # (_read_section) and probe helpers (_run_helper: probe_site,
    # probe_plants, probe_material, ...) all read game structures,
    # so they must happen while the game is verified paused. The
    # gate pauses first (if running) and restores the entry pause
    # state afterwards; the action's own _wait_for_paused bursts nest
    # inside it (they restore to paused, which is what the gate
    # established). A refused read fails the action as "transport"
    # (outcome unknown), never reads while running.
    # Deferred import: read_safety imports from this module.
    from .read_safety import ReadRefused, paused_read
    try:
        result = paused_read(client, lambda: fn(client, **kwargs))
    except ReadRefused as exc:
        result = ActionResult(
            ok=False, action=name,
            reason=f"read refused: {exc}",
            error_kind="transport",
            took_ms=round((time.monotonic() - started) * 1000))
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
    # Failure diagnosis (GOAL.md step 5, layer 4): a failed action
    # carries its fix (the corrective action + what it needs), so the
    # agent never repeats it with the same approach. No state, no
    # fix — the result stands on its reason alone.
    if not result.ok and state is not None:
        from .diagnose import diagnose_failure
        result.fix = diagnose_failure(
            name, result.reason, result.error_kind, state)
    return result
