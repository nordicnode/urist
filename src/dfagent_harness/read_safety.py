"""Read safety: pause-before-read (world-model design §8).

The invariant: **no world-state read while the game is running.
Every read happens while the game is verified paused.**

While running, the harness listens (the eventful watcher writes a
file; the drainer reads the file, not game memory). While paused, it
reads (RPC). If pause cannot be verified, the read is refused —
"outcome unknown" — never performed while running, never retried
while running.

This module is the single implementation of that gate. Every read
site (planner tick, poller, run_task, HTTP/CLI) goes through it, or
through the poller's skip-if-running variant below.

The crash evidence (2026-11-25): the chop test killed DF three
times in one night; one run ended ``free(): double free detected in
tcache 2``, another showed ``RPC call of invalid id 41``. The leading
hypothesis is a race: RPC reads of game structures (jobs list, units)
while the game ticks can catch a freed struct. The pause rule stands
until DFHack r8 RPC Lua atomicity is proven otherwise (design §8.5).
"""

from __future__ import annotations

from typing import Any, Callable

from dfhack_rpc import DFHackClient

from .actions import _Fail, get_paused, set_paused


class ReadRefused(Exception):
    """A world-state read was refused: pause could not be verified.

    The read was NOT performed. The caller treats the outcome as
    unknown and retries on a later cycle, after re-verifying pause.
    Never retry while running.
    """


def paused_read(client: DFHackClient, read_fn: Callable[[], Any],
                *, restore: bool = True) -> Any:
    """Run ``read_fn`` while the game is verified paused.

    Records the entry pause state, pauses (verified) if the game was
    running, runs ``read_fn``, then restores the entry pause state.
    Raises :class:`ReadRefused` if pause cannot be verified — the
    read is not performed. A restore failure propagates as the
    underlying verification failure (mirroring
    ``actions._wait_for_paused``): the read already happened while
    paused, so it was safe, but the caller must know the pause state
    is uncertain.

    The caller must hold the daemon's RPC lock across this call, so
    no other thread can unpause the game between the pause check and
    the read. (The daemon passes one RLock to the planner, the
    poller, and the HTTP server.)
    """
    was_paused = get_paused(client)
    if not was_paused:
        try:
            set_paused(client, True)
        except _Fail as exc:
            raise ReadRefused(
                f"pause could not be verified: {exc}") from exc
    try:
        return read_fn()
    finally:
        if restore and get_paused(client) != was_paused:
            set_paused(client, was_paused)
