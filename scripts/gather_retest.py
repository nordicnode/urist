#!/usr/bin/env python3
"""Gather re-test: does the sweep create GatherPlants jobs from a
shrub-rich designation, and do dwarves work them?

The previous control (2026-11-26) used a 1-shrub box and saw 0
GatherPlants jobs over 60 s + 8 bursts — inconclusive, not proof
gather is broken (the previous coordinator had observed GatherPlants
jobs spawning and being worked, and act_plants sets the block flag).
This re-test uses a shrub-rich 10x10 box and watches for jobs +
gathered plants over short unpause bursts.

Usage:
    .venv/bin/python scripts/gather_retest.py [--timeout 45] [--burst-s 1.0]
Prints a verdict line and exits 0 when jobs spawn and plants are
gathered, 1 otherwise. Leaves the game paused; clears the
designation afterwards.
"""
import argparse
import sys
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "src"))

from dfagent_harness import actions  # noqa: E402
from dfagent_harness.observe import collect  # noqa: E402
from dfagent_harness.read_safety import paused_read  # noqa: E402
from dfhack_rpc import DFHackClient  # noqa: E402


def count_gather_jobs(client) -> int:
    s = paused_read(client, lambda: collect(client, sections=("jobs",)))
    jobs = (s.get("jobs") or {}).get("list") or []
    return sum(1 for j in jobs if j.get("type") == "GatherPlants")


def count_plants(client) -> int:
    s = paused_read(client, lambda: collect(client, sections=("items",)))
    items = s.get("items") or {}
    total = 0
    for e in items.get("by_type") or []:
        if e.get("type") == "PLANT":
            total += int(e.get("units") or 0)
    return total


def find_shrub_box(client, surface_z: int):
    """Probe the whole surface for shrubs; return the densest 10x10
    box (x0,y0,z,x1,y1,z) and the shrub count inside it."""
    probe = actions._run_helper(
        client, "probe_plants.lua",
        {"x0": 0, "y0": 0, "z0": surface_z,
         "x1": 191, "y1": 191, "z1": surface_z, "kind": "shrub"})
    plants = probe.get("plants") or []
    if not plants:
        return None, 0
    # Densest 10x10 box over the shrub positions.
    best, best_box = 0, None
    xs = sorted({p["pos"][0] for p in plants})
    ys = sorted({p["pos"][1] for p in plants})
    for x0 in xs:
        for y0 in ys:
            n = sum(1 for p in plants
                    if x0 <= p["pos"][0] < x0 + 10
                    and y0 <= p["pos"][1] < y0 + 10)
            if n > best:
                best, best_box = n, (x0, y0, surface_z,
                                     x0 + 9, y0 + 9, surface_z)
    return best_box, best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--burst-s", type=float, default=1.0)
    args = ap.parse_args()

    client = DFHackClient("127.0.0.1", 5000, timeout=10.0)
    client.connect()
    state = paused_read(client, lambda: collect(client))
    citizens = (state.get("units") or {}).get("citizens") or []
    surface_z = min(c["pos"][2] for c in citizens if c.get("pos"))
    print(f"surface z={surface_z}, citizens={len(citizens)}", flush=True)
    box, n = find_shrub_box(client, surface_z)
    if box is None:
        print("VERDICT: no shrubs on the surface at all", flush=True)
        return 1
    print(f"densest 10x10 box {box} holds {n} shrubs", flush=True)
    plants_before = count_plants(client)
    print(f"PLANT units in stock before: {plants_before}", flush=True)

    res = actions.act(client, "designate_gather", box=box)
    print(f"designate: ok={res.ok} "
          f"marked={res.after.get('marked')}/{res.after.get('total')}",
          flush=True)
    if not res.ok:
        print(f"VERDICT: designation failed: {res.reason}", flush=True)
        return 1

    max_jobs = 0
    gathered = 0
    try:
        # One bounded wait: bursts of 1 s (~46 game ticks each) until
        # a GatherPlants job spawns or plants are gathered, or the
        # timeout (45 s wall ~ 2000 ticks ~ 1.7 days ~ 0.85 drink).
        # The predicate runs while paused (read safety).
        seen = {"jobs": 0}

        def _predicate():
            jobs = count_gather_jobs(client)
            seen["jobs"] = max(seen["jobs"], jobs)
            plants = count_plants(client)
            print(f"  check: GatherPlants jobs={jobs} "
                  f"plants in stock={plants}", flush=True)
            return jobs > 0 or plants > plants_before

        found = actions._wait_for_paused(
            client, _predicate, timeout=args.timeout, burst=args.burst_s)
        max_jobs = seen["jobs"]
        if found:
            # Jobs spawned — give dwarves a few more bursts to work
            # them and gather plants.
            def _gathered():
                return count_plants(client) > plants_before

            actions._wait_for_paused(
                client, _gathered, timeout=20.0, burst=args.burst_s)
    finally:
        actions.act(client, "designate_gather", box=box, mark=False)
        print("designation cleared", flush=True)

    plants_after = count_plants(client)
    gathered = plants_after - plants_before
    print(f"max GatherPlants jobs seen: {max_jobs}; "
          f"plants gathered: {gathered} "
          f"({plants_before} -> {plants_after})", flush=True)
    if max_jobs > 0 and gathered > 0:
        print("VERDICT: gather WORKS — jobs spawn and dwarves "
              "gather plants", flush=True)
        return 0
    if max_jobs > 0:
        print("VERDICT: jobs spawn but no plants gathered yet "
              "(dwarves may still be en route)", flush=True)
        return 0
    print("VERDICT: NO GatherPlants jobs spawned — gather is "
          "broken (same failure as dig had)", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
